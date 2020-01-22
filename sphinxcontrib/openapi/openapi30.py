"""
    sphinxcontrib.openapi.openapi30
    -------------------------------

    The OpenAPI 3.0.0 spec renderer. Based on ``sphinxcontrib-httpdomain``.

    :copyright: (c) 2016, Ihor Kalnytskyi.
    :license: BSD, see LICENSE for details.
"""

import copy
import collections
from datetime import datetime
import itertools
import json
import re
from urllib import parse
from http.client import responses as http_status_codes

from sphinx.util import logging

from sphinxcontrib.openapi import utils


LOG = logging.getLogger(__name__)

# https://github.com/OAI/OpenAPI-Specification/blob/3.0.2/versions/3.0.0.md#data-types
_TYPE_MAPPING = {
    ('integer', 'int32'): 1,  # integer
    ('integer', 'int64'): 1,  # long
    ('number', 'float'): 1.0,  # float
    ('number', 'double'): 1.0,  # double
    ('boolean', None): True,  # boolean
    ('string', None): 'string',  # string
    ('string', 'byte'): 'c3RyaW5n',  # b'string' encoded in base64,  # byte
    ('string', 'binary'): '01010101',  # binary
    ('string', 'date'): datetime.now().date().isoformat(),  # date
    ('string', 'date-time'): datetime.now().isoformat(),  # dateTime
    ('string', 'password'): '********',  # password

    # custom extensions to handle common formats
    ('string', 'email'): 'name@example.com',
    ('string', 'zip-code'): '90210',
    ('string', 'uri'): 'https://example.com',

    # additional fallthrough cases
    ('integer', None): 1,  # integer
    ('number', None): 1.0,  # <fallthrough>
}

_READONLY_PROPERTY = object()  # sentinel for values not included in requests


def _dict_merge(dct, merge_dct):
    """Recursive dict merge.

    Inspired by :meth:``dict.update()``, instead of updating only top-level
    keys, dict_merge recurses down into dicts nested to an arbitrary depth,
    updating keys. The ``merge_dct`` is merged into ``dct``.

    From https://gist.github.com/angstwad/bf22d1822c38a92ec0a9

    Arguments:
        dct: dict onto which the merge is executed
        merge_dct: dct merged into dct
    """
    for k, v in merge_dct.items():
        if (k in dct and isinstance(dct[k], dict)
                and isinstance(merge_dct[k], collections.Mapping)):
            _dict_merge(dct[k], merge_dct[k])
        else:
            dct[k] = merge_dct[k]


def _parse_schema(schema, method):
    """
    Convert a Schema Object to a Python object.

    Args:
        schema: An ``OrderedDict`` representing the schema object.
    """
    if method and schema.get('readOnly', False):
        return _READONLY_PROPERTY

    # allOf: Must be valid against all of the subschemas
    if 'allOf' in schema:
        schema_ = copy.deepcopy(schema['allOf'][0])
        for x in schema['allOf'][1:]:
            _dict_merge(schema_, x)

        return _parse_schema(schema_, method)

    # anyOf: Must be valid against any of the subschemas
    # TODO(stephenfin): Handle anyOf

    # oneOf: Must be valid against exactly one of the subschemas
    if 'oneOf' in schema:
        # we only show the first one since we can't show everything
        return _parse_schema(schema['oneOf'][0], method)

    if 'enum' in schema:
        # we only show the first one since we can't show everything
        return schema['enum'][0]

    schema_type = schema.get('type', 'object')

    if schema_type == 'array':
        # special case oneOf so that we can show examples for all possible
        # combinations
        if 'oneOf' in schema['items']:
            return [
                _parse_schema(x, method) for x in schema['items']['oneOf']]

        return [_parse_schema(schema['items'], method)]

    if schema_type == 'object':
        if method and 'properties' in schema and \
                all(v.get('readOnly', False)
                    for v in schema['properties'].values()):
            return _READONLY_PROPERTY

        results = []
        for name, prop in schema.get('properties', {}).items():
            result = _parse_schema(prop, method)
            if result != _READONLY_PROPERTY:
                results.append((name, result))

        return collections.OrderedDict(results)

    if (schema_type, schema.get('format')) in _TYPE_MAPPING:
        return _TYPE_MAPPING[(schema_type, schema.get('format'))]

    return _TYPE_MAPPING[(schema_type, None)]  # unrecognized format


def _example(media_type_objects, method=None, endpoint=None, status=None,
             nb_indent=0):
    """
    Format examples in `Media Type Object` openapi v3 to HTTP request or
    HTTP response example.
    If method and endpoint is provided, this function prints a request example
    else status should be provided to print a response example.

    Arguments:
        media_type_objects (Dict[str, Dict]): Dict containing
            Media Type Objects.
        method: The HTTP method to use in example.
        endpoint: The HTTP route to use in example.
        status: The HTTP status to use in example.
    """
    indent = '   '
    extra_indent = indent * nb_indent

    if method is not None:
        method = method.upper()
    else:
        try:
            # one of possible values for status might be 'default'.
            # in the case, just fallback to '-'
            status_text = http_status_codes[int(status)]
        except (ValueError, KeyError):
            status_text = '-'

    # Provide request samples for GET requests
    if method == 'GET':
        media_type_objects[''] = {
            'examples': {'Example request': {'value': ''}}}

    for content_type, content in media_type_objects.items():
        examples = content.get('examples')
        example = content.get('example')

        if examples is None:
            examples = {}
            if not example:
                if re.match(r"application/[a-zA-Z\+]*json", content_type) is \
                        None:
                    LOG.info('skipping non-JSON example generation.')
                    continue
                example = _parse_schema(content['schema'], method=method)

            if method is None:
                examples['Example response'] = {
                    'value': example,
                }
            else:
                examples['Example request'] = {
                    'value': example,
                }

        for example in examples.values():
            if not isinstance(example['value'], str):
                example['value'] = json.dumps(
                    example['value'], indent=4, separators=(',', ': '))

        for example_name, example in examples.items():
            if 'summary' in example:
                example_title = '{example_name} - {example[summary]}'.format(
                    **locals())
            else:
                example_title = example_name

            yield ''
            yield '{extra_indent}**{example_title}:**'.format(**locals())
            yield ''
            yield '{extra_indent}.. sourcecode:: http'.format(**locals())
            yield ''

            # Print http request example
            if method:
                yield '{extra_indent}{indent}{method} {endpoint} HTTP/1.1' \
                    .format(**locals())
                yield '{extra_indent}{indent}Host: example.com' \
                    .format(**locals())
                if content_type:
                    yield '{extra_indent}{indent}Content-Type: {content_type}'\
                        .format(**locals())

            # Print http response example
            else:
                yield '{extra_indent}{indent}HTTP/1.1 {status} {status_text}' \
                    .format(**locals())
                yield '{extra_indent}{indent}Content-Type: {content_type}' \
                    .format(**locals())

            yield ''
            for example_line in example['value'].splitlines():
                yield '{extra_indent}{indent}{example_line}'.format(**locals())
            if example['value'].splitlines():
                yield ''


def _httpresource(endpoint, method, properties, convert, render_examples,
                  render_request):
    # https://github.com/OAI/OpenAPI-Specification/blob/3.0.2/versions/3.0.0.md#operation-object
    parameters = properties.get('parameters', [])
    responses = properties['responses']
    query_param_examples = []
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

    # print request's path params
    for param in filter(lambda p: p['in'] == 'path', parameters):
        yield indent + ':param {type} {name}:'.format(
            type=param['schema']['type'],
            name=param['name'])

        for line in convert(param.get('description', '')).splitlines():
            yield '{indent}{indent}{line}'.format(**locals())

    # print request's query params
    for param in filter(lambda p: p['in'] == 'query', parameters):
        yield indent + ':query {type} {name}:'.format(
            type=param['schema']['type'],
            name=param['name'])
        for line in convert(param.get('description', '')).splitlines():
            yield '{indent}{indent}{line}'.format(**locals())
        if param.get('required', False):
            yield '{indent}{indent}(Required)'.format(**locals())
            example = _parse_schema(param['schema'], method)
            example = param.get('example', example)
            if param.get('explode', False) and isinstance(example, list):
                for v in example:
                    query_param_examples.append((param['name'], v))
            elif param.get('explode', False) and isinstance(example, dict):
                for k, v in example.items():
                    query_param_examples.append((k, v))
            else:
                query_param_examples.append((param['name'], example))

    # print request content
    if render_request:
        yield ''
        request_content = properties.get('requestBody', {}).get('content', {})
        if request_content and 'application/json' in request_content:
            schema = request_content['application/json']['schema']
            schs = []
            if 'oneOf' in schema:
                schs = schema['oneOf']
            else:
                schs = [schema]
            if len(schs) > 1:
                yield ('{indent}The request accepts '
                       'the following bodies:'.format(**locals()))
                yield ''
            for sch in schs:
                req_properties = json.dumps(sch['properties'], indent=2,
                                            separators=(',', ':'))
                yield '{indent}**Request body:**'.format(**locals())
                yield ''
                yield '{indent}.. sourcecode:: json'.format(**locals())
                yield ''
                for line in req_properties.splitlines():
                    # yield indent + line
                    yield '{indent}{indent}{line}'.format(**locals())
                    # yield ''
                yield ''

    # print request example
    if render_examples:
        endpoint_examples = endpoint
        if query_param_examples:
            endpoint_examples = endpoint + "?" + \
                parse.urlencode(query_param_examples)

        # print request example
        request_content = properties.get('requestBody', {}).get('content', {})
        for line in _example(
                request_content,
                method,
                endpoint=endpoint_examples,
                nb_indent=1):
            yield line

    # print response status codes
    for status, response in responses.items():
        yield '{indent}:status {status}:'.format(**locals())
        for line in convert(response['description']).splitlines():
            yield '{indent}{indent}{line}'.format(**locals())

        # print response example
        if render_examples:
            for line in _example(
                    response.get('content', {}), status=status, nb_indent=2):
                yield line

    # print request header params
    for param in filter(lambda p: p['in'] == 'header', parameters):
        yield indent + ':reqheader {name}:'.format(**param)
        for line in convert(param.get('description', '')).splitlines():
            yield '{indent}{indent}{line}'.format(**locals())
        if param.get('required', False):
            yield '{indent}{indent}(Required)'.format(**locals())

    # print response headers
    for status, response in responses.items():
        for headername, header in response.get('headers', {}).items():
            yield indent + ':resheader {name}:'.format(name=headername)
            for line in convert(header['description']).splitlines():
                yield '{indent}{indent}{line}'.format(**locals())

    for cb_name, cb_specs in properties.get('callbacks', {}).items():
        yield ''
        yield indent + '.. admonition:: Callback: ' + cb_name
        yield ''

        for cb_endpoint in cb_specs.keys():
            for cb_method, cb_properties in cb_specs[cb_endpoint].items():
                for line in _httpresource(
                        cb_endpoint,
                        cb_method,
                        cb_properties,
                        convert=convert,
                        render_examples=render_examples,
                        render_request=render_request):
                    if line:
                        yield indent+indent+line
                    else:
                        yield ''

    yield ''


def _header(title):
    yield title
    yield '=' * len(title)
    yield ''


def openapihttpdomain(spec, **options):
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

    render_request = False
    if 'request' in options:
        render_request = True

    convert = utils.get_text_converter(options)

    # https://github.com/OAI/OpenAPI-Specification/blob/3.0.2/versions/3.0.0.md#paths-object
    if 'group' in options:
        groups = collections.OrderedDict(
            [(x['name'], []) for x in spec.get('tags', {})]
            )

        for endpoint in paths:
            for method, properties in spec['paths'][endpoint].items():
                key = properties.get('tags', [''])[0]
                groups.setdefault(key, []).append(_httpresource(
                    endpoint,
                    method,
                    properties,
                    convert,
                    render_examples='examples' in options,
                    render_request=render_request))

        for key in groups.keys():
            if key:
                generators.append(_header(key))
            else:
                generators.append(_header('default'))

            generators.extend(groups[key])
    else:
        for endpoint in paths:
            for method, properties in spec['paths'][endpoint].items():
                generators.append(_httpresource(
                    endpoint,
                    method,
                    properties,
                    convert,
                    render_examples='examples' in options,
                    render_request=render_request))

    return iter(itertools.chain(*generators))
