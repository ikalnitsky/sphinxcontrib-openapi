=====================
sphinxcontrib-openapi
=====================

.. hint::

    Check out `sphinxcontrib-redoc`_ if you are interested in separate
    three-panel OpenAPI spec rendering.

**sphinxcontrib-openapi** is a `Sphinx`_ extension to generate APIs docs from
`OpenAPI`_ (fka Swagger) spec. It depends on `sphinxcontrib-httpdomain`_ that
provides an HTTP domain for describing RESTful HTTP APIs, so we don't need to
reinvent the wheel.

.. code:: bash

   pip install sphinxcontrib-openapi


How To Use?
===========

Consider you have the following OpenAPI spec saved at ``specs/openapi.yml``:

.. literalinclude:: specs/openapi.yml
   :language: yaml

You can render it by using the ``openapi`` directive:

.. code:: restructuredtext

   .. openapi:: specs/openapi.yml

and it will be rendered into something like:

.. openapi:: specs/openapi.yml


Options
=======

The ``openapi`` directive supports the following options:

``encoding``
  Encoding to be used to read an OpenAPI spec. If not passed, Sphinx's
  source encoding will be used.

``paths``
  A comma separated list of paths to filter the included OpenAPI spec by.
  For example:

  .. code:: restructuredtext

     .. openapi:: specs/openapi.yml
        :paths:
           /persons
           /evidence
        :encoding: utf-8

  Would only render the endpoints at ``/persons`` and ``/evidence``,
  ignoring all others.

``examples``
  If passed, both request and response examples will be rendered. Please
  note, if examples are not provided in a spec, they will be generated
  by internal logic based on a corresponding schema.

``group``
  If passed, paths will be grouped by tags. If a path has no tag assigned, it
  will be grouped in a ``default`` group.

``format``
  The format of text in the spec, either ``rst`` or ``markdown``. If
  not supplied, ReStructured Text is assumed.

``include``
  A line separated list of regular expressions to filter the included openapi
  spec by. For example:

  .. code:: restructuredtext

     .. openapi:: specs/openapi.yml
        :include:
           /evid.*
        :encoding: utf-8

  Would render the endpoints at ``/evidence`` and ``/evidence/{pk}``

``exclude``
  A line separated list of regular expressions to filter the included openapi
  spec by (excluding matches). For example:

  .. code:: restructuredtext

     .. openapi:: specs/openapi.yml
        :exclude:
           /evidence/{pk}
        :encoding: utf-8

  Would render ``/persons`` and ``/evidence`` endpoints, but not
  ``/evidence/{pk}`` endpoints

``methods``
  A line separated list of http methods to filter included openapi
  spec. For example:

  .. code:: restructuredtext

     .. openapi:: specs/openapi.yml
        :methods:
            get
            post
            put
        :encoding: utf-8

  Would render paths with get, post or put method

``exclude``, ``include`` and ``paths`` can also be used together (``exclude``
taking precedence over ``include`` and ``paths``)

``http-methods-order``
  A whitespace delimited list of HTTP methods to render first. For example:

  .. code:: restructuredtext

     .. openapi:: specs/openapi.yml
        :http-methods-order:
            head
            get

  Would render the ``head`` method, followed by the ``get`` method, followed by the rest of the methods in their declared ordered.

``openapi_default_renderer``
  A string to select the renderer.

  Currently has two options:

    * ``httpdomain:old`` Old HTTP renderer. Well tested but lacks support for JSON schemas. Default.
    * ``httpdomain`` New renderer with support for JSON schemas but not as well tested.


.. _Sphinx: https://www.sphinx-doc.org/en/master/
.. _OpenAPI: https://github.com/OAI/OpenAPI-Specification
.. _sphinxcontrib-httpdomain: https://sphinxcontrib-httpdomain.readthedocs.io/
.. _sphinxcontrib-redoc: https://sphinxcontrib-redoc.readthedocs.io/
