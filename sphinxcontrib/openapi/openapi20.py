"""
    sphinxcontrib.openapi.openapi20
    -------------------------------

    The OpenAPI 2.0 (f.k.a. Swagger) spec renderer. Based on
    ``sphinxcontrib-httpdomain``.

    :copyright: (c) 2016, Ihor Kalnytskyi.
    :license: BSD, see LICENSE for details.
"""

import collections
import itertools
import re

from sphinxcontrib.openapi import utils


def _httpresource(endpoint, method, properties, convert):
    parameters = properties.get('parameters', [])
    responses = properties['responses']
    indent = '   '

    yield '.. http:{0}:: {1}'.format(method, endpoint)
    yield '   :synopsis: {0}'.format(properties.get('summary', 'null'))
    yield ''

    if 'summary' in properties:
        for line in properties['summary'].splitlines():
            yield '{indent}**{line}**'.format(**locals())
        yield ''

    if 'description' in properties:
        for line in convert(properties['description']).splitlines():
            yield '{indent}{line}'.format(**locals())
        yield ''

    for param in filter(lambda p: p['in'] == 'path', parameters):
        yield indent + ':param {type} {name}:'.format(**param)
        for line in convert(param.get('description', '')).splitlines():
            yield '{indent}{indent}{line}'.format(**locals())

    # print request's query params
    for param in filter(lambda p: p['in'] == 'query', parameters):
        yield indent + ':query {type} {name}:'.format(**param)
        for line in convert(param.get('description', '')).splitlines():
            yield '{indent}{indent}{line}'.format(**locals())

    # print the json body params
    for param in filter(lambda p: p['in'] == 'body', parameters):
        if 'schema' in param:
            yield ''
            for line in convert_json_schema(param['schema']):
                yield '{indent}{line}'.format(**locals())
            yield ''

    # print response status codes
    for status, response in sorted(responses.items()):
        yield '{indent}:status {status}:'.format(**locals())
        for line in convert(response['description']).splitlines():
            yield '{indent}{indent}{line}'.format(**locals())

    # print request header params
    for param in filter(lambda p: p['in'] == 'header', parameters):
        yield indent + ':reqheader {name}:'.format(**param)
        for line in convert(param.get('description', '')).splitlines():
            yield '{indent}{indent}{line}'.format(**locals())

    # print response headers
    for status, response in responses.items():
        for headername, header in response.get('headers', {}).items():
            yield indent + ':resheader {name}:'.format(name=headername)
            for line in convert(header['description']).splitlines():
                yield '{indent}{indent}{line}'.format(**locals())

    for status, response in responses.items():
        if not is_2xx_response(status):
            continue
        if 'schema' in response:
            yield ''
            for line in convert_json_schema(
                    response['schema'], directive=':>json'):
                yield '{indent}{line}'.format(**locals())
            yield ''

    yield ''


def convert_json_schema(schema, directive=':<json'):
    """
    Convert json schema to `:<json` sphinx httpdomain.
    """

    output = []

    def _convert(schema, name='', required=False):
        """
        Fill the output list, with 2-tuple (name, template)

        i.e: ('user.age', 'str user.age: the age of user')

        This allow to sort output by field name
        """

        type_ = schema.get('type', 'any')
        required_properties = schema.get('required', ())
        if type_ == 'object' and schema.get('properties'):
            for prop, next_schema in schema.get('properties', {}).items():
                _convert(
                    next_schema, '{name}.{prop}'.format(**locals()),
                    (prop in required_properties))

        elif type_ == 'array':
            name = name.lstrip('.')
            description = schema.get('description', '')
            output.append((
                name,
                '{type_} {name}:'
                ' {description}'.format(**locals())))
            if schema['items'].get('type', 'any') not in ['string', 'number', 'integer', 'boolean']:
                _convert(schema['items'], name + '[]')

        else:
            if name:
                name = name.lstrip('.')
                constraints = []
                if required:
                    constraints.append('required')
                if schema.get('readOnly', False):
                    constraints.append('read only')
                if constraints:
                    constraints = '({})'.format(', '.join(constraints))
                else:
                    constraints = ''

                if schema.get('description', ''):
                    if constraints:
                        output.append((
                            name,
                            '{type_} {name}:'
                            ' {schema[description]}'
                            ' {constraints}'.format(**locals())))
                    else:
                        output.append((
                            name,
                            '{type_} {name}:'
                            ' {schema[description]}'.format(**locals())))

                else:
                    if constraints:
                        output.append(
                            (name,
                             '{type_} {name}:'
                             ' {constraints}'.format(**locals())))
                    else:
                        output.append(
                            (name,
                             '{type_} {name}:'.format(**locals())))

    _convert(schema)

    for _, render in sorted(output):
        yield '{} {}'.format(directive, render)


def is_2xx_response(status):
    try:
        status = int(status)
        return 200 <= status < 300
    except ValueError:
        pass
    return False


def _header(title):
    yield title
    yield '=' * len(title)
    yield ''


def openapihttpdomain(spec, **options):
    if 'examples' in options:
        raise ValueError(
            'Rendering examples is not supported for OpenAPI v2.x specs.')

    if 'request' in options:
        raise ValueError(
            'The :request: option is not supported for OpenAPI v2.x specs.')

    generators = []

    # OpenAPI spec may contain JSON references, common properties, etc.
    # Trying to render the spec "As Is" will require to put multiple
    # if-s around the code. In order to simplify flow, let's make the
    # spec to have only one (expected) schema, i.e. normalize it.
    utils.normalize_spec(spec, **options)

    # Paths list to be processed
    paths = []

    # If 'paths' are passed we've got to ensure they exist within an OpenAPI
    # spec; otherwise raise error and ask user to fix that.
    if 'paths' in options:
        if not set(options['paths']).issubset(spec['paths']):
            raise ValueError(
                'One or more paths are not defined in the spec: %s.' % (
                    ', '.join(set(options['paths']) - set(spec['paths'])),
                )
            )
        paths = options['paths']

    # Check against regular expressions to be included
    if 'include' in options:
        for i in options['include']:
            ir = re.compile(i)
            for path in spec['paths']:
                if ir.match(path):
                    paths.append(path)

    # If no include nor paths option, then take full path
    if 'include' not in options and 'paths' not in options:
        paths = spec['paths']

    # Remove paths matching regexp
    if 'exclude' in options:
        _paths = []
        for e in options['exclude']:
            er = re.compile(e)
            for path in paths:
                if not er.match(path):
                    _paths.append(path)
        paths = _paths

    if 'group' in options:
        groups = collections.OrderedDict(
            [(x['name'], []) for x in spec.get('tags', {})]
        )

        for endpoint in paths:
            for method, properties in spec['paths'][endpoint].items():
                if options.get('methods') and method not in options.get('methods'):
                    continue
                key = properties.get('tags', [''])[0]
                groups.setdefault(key, []).append(_httpresource(
                    endpoint,
                    method,
                    properties,
                    utils.get_text_converter(options),
                ))

        for key in groups.keys():
            if key:
                generators.append(_header(key))
            else:
                generators.append(_header('default'))

            generators.extend(groups[key])
    else:
        for endpoint in paths:
            for method, properties in spec['paths'][endpoint].items():
                if options.get('methods') and method not in options.get('methods'):
                    continue
                generators.append(_httpresource(
                    endpoint,
                    method,
                    properties,
                    utils.get_text_converter(options),
                ))

    return iter(itertools.chain(*generators))
