# Contributing

Contributions are very welcome. The best way to contribute is to first get in contact
with us by filing an issue to see if your proposed changes agree with
our plans for the project.

Apart from contributing actual code, improvements of the documentations or
just bug-report or enhancement requests are also a good way to contribute.

## Coding guidelines

We use black to format our code and pre-commit to ensure that all
commits run black before being commited.

Also please run the tests using
```
python -m pytest
```
before submitting any code.

To get a copy of the repository, you can clone it using

```
git clone git@bitbucket.org:berkeleylab/pypixie16.git
```

To enable the git-pre-commit hooks, please run

```
pip install pre-commit
pre-commit install
```

from within the git repository.

And use the issue tracker and pull requests in bitbucket.

