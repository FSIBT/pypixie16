# Contributing

Contributions are very welcome. The best way to contribute is to first get in contact
with us by filing an issue to see if your proposed changes can be easily added to the project.

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
git clone git@github.com:FSIBT/pypixie16.git
```

To enable the git-pre-commit hooks, please run

```
pip install pre-commit
pre-commit install
```

from within the git repository.

And use the [issue tracker](https://github.com/FSIBT/pypixie16/issues) and pull requests on GitHub.

## Making a release

Move the entries in `CHANGELOG.md` from *Unreleased* to a new section
for the version, commit this to `main`, and then create and push a tag
that starts with `v`:

```
git tag -a v3.2.0 -m "Release 3.2.0"
git push origin v3.2.0
```

The tag runs the tests, waits for a maintainer to approve the deployment
in GitHub Actions, publishes the package on PyPI and creates a GitHub
release that uses the changelog section as release notes.
