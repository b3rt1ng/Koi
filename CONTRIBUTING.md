# Contributing to Koi

Contributions to Koi have to follow these few rules:

- Modules have to use the blueprint and its dedicated methods. Check out the [blueprint.py](src/koi/modules/blueprint.py) where everything is documented.
- Security reports have to follow the guidelines explained [here](https://github.com/b3rt1ng/Koi?tab=security-ov-file).
- Inner Koi functions or core functionalities have to be kept as light as technically possible. This does not exclude tricky or comically annoying protocols to implement, if it's necessary, give it a shot, we'll see how pertinent it is (we're talking about you, Microsoft devs).
- Implementations need to keep Koi safe to use for the user, making sure that it will not have unexpected behavior (removing files with a poorly implemented regex or pattern matching, etc.).

###### Use of AI:
I am not completely against the use of AI when it comes to contributions. But if you do use it, make sure that it has full context of Koi's implementation, it does not make oversimplifications, it does not introduce vulnerabilities, etc.

And on top of all, please make the code readable. I'm the one reviewing it and I need to understand what's going on.

#### Go check out the wiki

I made a [wiki](https://b3rt1ng.github.io/koi-wiki/) and I try to keep it as updated as possible, you can check it out yourself!