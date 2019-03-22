from setuptools import setup

setup(name='pypixie16',
      version='0.1',
      description='Python library to control a pixie16 module from XIA',
      url='https://bitbucket.org/berkeleylab/pypixie16',
      author='Arun Persaud',
      author_email='apersaud@lbl.gov',
      license='modified BSD',
      packages=['pypixie16'],
      install_requires=['docopt', 'numpy', 'appdirs', 'mpmath'],
      zip_safe=False)
