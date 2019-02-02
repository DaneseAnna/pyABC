.. _code:

Contributing Code
=================

Testing
-------

We're commited to testing our code. Tests are run on Travis CI.
We encourage to test whatever possible. However, it might not always be easy to
test code which is based on random sampling. We still encourage to provide general sanity
and intergation tests. We highly encourage a
`test-driven development (TDD) <http://en.wikipedia.org/wiki/Test-driven_development>`_ style.

Python (PEP8)
~~~~~~~~~~~~~

We try to respect the `PEP8 <http://www.python.org/dev/peps/pep-0008/>`_ standard.
We run `flake8 <http://flake8.pycqa.org/en/latest/>`_ as part of the test
suite. The tests won't pass if flake8 complains.

Writing tests
-------------

Test can be written with `pytest <http://docs.pytest.org/en/latest/>`_
or the `unittest <https://docs.python.org/3/library/unittest.html>`_ module.


Versioning scheme
-----------------

For version numbers, we use ``A.B.C``, where

* ``C`` is increased for bug fixes
* ``B`` is increased for new features
* ``A`` for API breaking, backwards incompatible changes.

That is, we follow the versioning scheme suggested
by the `Python packaging guide <https://packaging.python.org>`_.


Uploading to the Python package index PyPI
------------------------------------------

First, a so called "wheel" is created via

::

    python setup.py bdist_wheel

A wheel is essentially a zip archive which contains the source code
and the binaries (if any).
This archive is uploaded using twine


::

    twine upload dist/pyabc-x.y.z-py3-non-any.wheel

replacing x.y.z by the appropriate version number.

For a more in depth discussion see also the
`section on distributing packages <https://packaging.python.org/tutorials/distributing-packages>`_
of the Python packaging guide
