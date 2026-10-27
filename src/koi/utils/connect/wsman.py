from __future__ import annotations

import base64
import http.client
import ssl
import uuid
from typing import Optional
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape as _xml_escape

from koi.utils.connect import ntlm
from koi.utils.connect.base import TransportError

_CONTENT_TYPE = 'application/soap+xml;charset=UTF-8'
_TIMEOUT = 30

_RSP = 'http://schemas.microsoft.com/wbem/wsman/1/windows/shell'
_RESOURCE_CMD = _RSP + '/cmd'

_ACTION_CREATE = 'http://schemas.xmlsoap.org/ws/2004/09/transfer/Create'
_ACTION_COMMAND = _RSP + '/Command'
_ACTION_RECEIVE = _RSP + '/Receive'
_ACTION_SEND = _RSP + '/Send'
_ACTION_SIGNAL = _RSP + '/Signal'
_ACTION_DELETE = 'http://schemas.xmlsoap.org/ws/2004/09/transfer/Delete'

_SIGNAL_TERMINATE = 'http://schemas.microsoft.com/wbem/wsman/1/windows/shell/signal/terminate'
_SIGNAL_CTRL_C = 'http://schemas.microsoft.com/wbem/wsman/1/windows/shell/signal/ctrl_c'

_XMLNS = (
    'xmlns:s="http://www.w3.org/2003/05/soap-envelope"'
    ' xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing"'
    ' xmlns:wsman="http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd"'
    ' xmlns:rsp="http://schemas.microsoft.com/wbem/wsman/1/windows/shell"'
)

_ANONYMOUS = 'http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous'


def _envelope(action: str, url: str, shell_id: Optional[str], body: str) -> str:
    selector = ''
    if shell_id:
        selector = (
            '<wsman:SelectorSet>'
            f'<wsman:Selector Name="ShellId">{shell_id}</wsman:Selector>'
            '</wsman:SelectorSet>'
        )
    return (
        f'<s:Envelope {_XMLNS}>'
        f'<s:Header>'
        f'<wsa:Action s:mustUnderstand="true">{action}</wsa:Action>'
        f'<wsa:To s:mustUnderstand="true">{url}</wsa:To>'
        f'<wsman:ResourceURI s:mustUnderstand="true">{_RESOURCE_CMD}</wsman:ResourceURI>'
        f'<wsa:MessageID>uuid:{uuid.uuid4()}</wsa:MessageID>'
        f'<wsa:ReplyTo>'
        f'<wsa:Address s:mustUnderstand="true">{_ANONYMOUS}</wsa:Address>'
        f'</wsa:ReplyTo>'
        f'<wsman:MaxEnvelopeSize s:mustUnderstand="true">153600</wsman:MaxEnvelopeSize>'
        f'<wsman:OperationTimeout>PT{_TIMEOUT}S</wsman:OperationTimeout>'
        f'{selector}'
        f'</s:Header>'
        f'<s:Body>{body}</s:Body>'
        f'</s:Envelope>'
    )


class WsManClient:

    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        nt_h: bytes,
        domain: str = '',
        use_ssl: bool = False,
    ) -> None:
        self._host = host
        self._port = port
        self._user = user
        self._nt_h = nt_h
        self._domain = domain
        self._use_ssl = use_ssl
        self._url = f'{"https" if use_ssl else "http"}://{host}:{port}/wsman'

    def _connect(self) -> http.client.HTTPConnection:
        if self._use_ssl:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            conn = http.client.HTTPSConnection(
                self._host, self._port, context=ctx, timeout=_TIMEOUT,
            )
        else:
            conn = http.client.HTTPConnection(
                self._host, self._port, timeout=_TIMEOUT,
            )
        return conn

    def _post(self, body: str) -> bytes:
        conn = self._connect()
        body_bytes = body.encode('utf-8')

        type1 = base64.b64encode(ntlm.negotiate()).decode()
        conn.request('POST', '/wsman', body=b'', headers={
            'Authorization': f'Negotiate {type1}',
            'Content-Type': _CONTENT_TYPE,
            'Content-Length': '0',
            'Connection': 'keep-alive',
        })
        resp = conn.getresponse()
        resp.read()

        if resp.status != 401:
            conn.close()
            raise TransportError(
                f'WinRM returned {resp.status} instead of 401 during NTLM negotiation '
                f'(is WinRM enabled on {self._host}:{self._port}?)',
            )

        auth_header = resp.getheader('WWW-Authenticate', '')
        if not auth_header.startswith('Negotiate '):
            conn.close()
            raise TransportError('WinRM did not return an NTLM challenge')

        type2 = base64.b64decode(auth_header.split(' ', 1)[1])
        type3 = base64.b64encode(
            ntlm.authenticate(type2, self._user, self._nt_h, self._domain),
        ).decode()

        conn.request('POST', '/wsman', body=body_bytes, headers={
            'Authorization': f'Negotiate {type3}',
            'Content-Type': _CONTENT_TYPE,
            'Connection': 'keep-alive',
        })
        resp = conn.getresponse()
        data = resp.read()
        conn.close()

        if resp.status == 401:
            raise TransportError('WinRM authentication failed (bad credentials or NTLM rejected)')
        if resp.status >= 400:
            try:
                fault = ET.fromstring(data)
                reason_el = fault.find('.//{http://www.w3.org/2003/05/soap-envelope}Text')
                detail = reason_el.text if reason_el is not None else data.decode('utf-8', errors='replace')[:300]
            except ET.ParseError:
                detail = data.decode('utf-8', errors='replace')[:300]
            raise TransportError(f'WinRM HTTP {resp.status}: {detail}')

        return data

    def create_shell(self) -> str:
        body = (
            '<rsp:Shell>'
            '<rsp:InputStreams>stdin</rsp:InputStreams>'
            '<rsp:OutputStreams>stdout stderr</rsp:OutputStreams>'
            '</rsp:Shell>'
        )
        data = self._post(_envelope(_ACTION_CREATE, self._url, None, body))
        root = ET.fromstring(data)
        el = root.find(f'.//{{{_RSP}}}ShellId')
        if el is None or not el.text:
            raise TransportError('WinRM did not return a ShellId')
        return el.text

    def run_command(self, shell_id: str, command: str, args: str = '') -> str:
        args_xml = f'<rsp:Arguments>{_xml_escape(args)}</rsp:Arguments>' if args else ''
        body = (
            f'<rsp:CommandLine>'
            f'<rsp:Command>{_xml_escape(command)}</rsp:Command>'
            f'{args_xml}'
            f'</rsp:CommandLine>'
        )
        data = self._post(_envelope(_ACTION_COMMAND, self._url, shell_id, body))
        root = ET.fromstring(data)
        el = root.find(f'.//{{{_RSP}}}CommandId')
        if el is None or not el.text:
            raise TransportError('WinRM did not return a CommandId')
        return el.text

    def receive_output(self, shell_id: str, command_id: str) -> tuple[bytes, bool]:
        """Poll stdout+stderr for *command_id*. Returns (data, done)."""
        body = (
            f'<rsp:Receive>'
            f'<rsp:DesiredStream CommandId="{command_id}">stdout stderr</rsp:DesiredStream>'
            f'</rsp:Receive>'
        )
        data = self._post(_envelope(_ACTION_RECEIVE, self._url, shell_id, body))
        root = ET.fromstring(data)

        out = b''
        for stream in root.findall(f'.//{{{_RSP}}}Stream'):
            if stream.text:
                out += base64.b64decode(stream.text)

        done = False
        state_el = root.find(f'.//{{{_RSP}}}CommandState')
        if state_el is not None:
            state = state_el.get('State', '')
            done = state.endswith('/Done')

        return out, done

    def send_input(self, shell_id: str, command_id: str, data: bytes) -> None:
        """Send stdin bytes to *command_id*."""
        b64 = base64.b64encode(data).decode()
        body = (
            f'<rsp:Send>'
            f'<rsp:Stream Name="stdin" CommandId="{command_id}">{b64}</rsp:Stream>'
            f'</rsp:Send>'
        )
        self._post(_envelope(_ACTION_SEND, self._url, shell_id, body))

    def signal_ctrl_c(self, shell_id: str, command_id: str) -> None:
        """Send Ctrl+C to *command_id*."""
        body = (
            f'<rsp:Signal CommandId="{command_id}">'
            f'<rsp:Code>{_SIGNAL_CTRL_C}</rsp:Code>'
            f'</rsp:Signal>'
        )
        try:
            self._post(_envelope(_ACTION_SIGNAL, self._url, shell_id, body))
        except TransportError:
            pass

    def signal_terminate(self, shell_id: str, command_id: str) -> None:
        """Send a terminate signal to *command_id*."""
        body = (
            f'<rsp:Signal CommandId="{command_id}">'
            f'<rsp:Code>{_SIGNAL_TERMINATE}</rsp:Code>'
            f'</rsp:Signal>'
        )
        try:
            self._post(_envelope(_ACTION_SIGNAL, self._url, shell_id, body))
        except TransportError:
            pass

    def delete_shell(self, shell_id: str) -> None:
        try:
            self._post(_envelope(_ACTION_DELETE, self._url, shell_id, ''))
        except TransportError:
            pass

    def close(self) -> None:
        pass
