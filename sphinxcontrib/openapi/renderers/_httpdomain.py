"""OpenAPI spec renderer."""

import functools
import http.client
import json

import docutils.parsers.rst.directives as directives
import m2r
import requests
import sphinx.util.logging as logging

from sphinxcontrib.openapi.renderers import abc


_DEFAULT_EXAMPLES = {
    "string": "string",
    "integer": 1,
    "number": 1.0,
    "boolean": True,
    "array": [],
}


_DEFAULT_STRING_EXAMPLES = {
    "date": "2020-01-01",
    "date-time": "2020-01-01T01:01:01Z",
    "password": "********",
    "byte": "QG1pY2hhZWxncmFoYW1ldmFucw==",
    "ipv4": "127.0.0.1",
    "ipv6": "::1",
}


logger = logging.getLogger(__name__)


def indented(generator, indent=3):
    for item in generator:
        if item:
            item = " " * indent + item
        yield item


def _iterexamples(media_type, example_preference, examples_from_schemas):
    if example_preference:
        order_by = dict(
            ((value, index) for index, value in enumerate(example_preference))
        )
        media_type = sorted(
            media_type.items(), key=lambda item: order_by.get(item[0], float("inf"))
        )
    else:
        media_type = media_type.items()

    for content_type, media_type in media_type:
        # Look for a example in a bunch of possible places. According to
        # OpenAPI v3 spec, `examples` and `example` keys are mutually
        # exclusive, so there's no much difference between their
        # inspection order, while both must take precedence over a
        # schema example.
        if media_type.get("examples", {}):
            for example in media_type["examples"].values():
                if "externalValue" in example:
                    if not example["externalValue"].startswith(("http://", "https://")):
                        logger.warning(
                            "Not supported protocol in 'externalValue': %s",
                            example["externalValue"],
                        )
                        continue

                    try:
                        response = requests.get(example["externalValue"])
                        response.raise_for_status()

                        example["value"] = response.text
                        example.pop("externalValue")
                    except Exception:
                        logger.error(
                            "Cannot retrieve example from: '%s'",
                            example["externalValue"],
                        )
                        continue
                break
            else:
                # If the loop over examples has not been interrupted, we
                # probably didn't find an example to render. In that case,
                # let's try and go next media type.
                continue
        elif media_type.get("example"):
            # Save example from "example" in "examples" compatible format. This
            # allows to treat all returned examples the same way.
            example = {"value": media_type["example"]}
        elif media_type.get("schema", {}).get("example"):
            # Save example from "schema" in "examples" compatible format. This
            # allows to treat all returned examples the same way.
            example = {"value": media_type["schema"]["example"]}
        elif "schema" in media_type and examples_from_schemas:
            # do some dark magic to convert schema to example
            example = {"value": _generate_example_from_schema(media_type["schema"])}
            pass
        else:
            continue

        yield content_type, example


class HttpdomainRenderer(abc.RestructuredTextRenderer):
    """Render OpenAPI v3 using `sphinxcontrib-httpdomain` extension."""

    _markup_converters = {"commonmark": m2r.convert, "restructuredtext": lambda x: x}

    option_spec = {
        "markup": functools.partial(directives.choice, values=_markup_converters),
        "request-parameters-order": None,
        "response-example-preference": "",
        "generate-example-from-schema": "",
    }

    def __init__(self, state, options):
        super().__init__(state, options)

        self._convert_markup = self._markup_converters[
            options.get("markup", "commonmark")
        ]
        self._request_parameters_order = ["header", "path", "query", "cookie"]
        self._response_example_preference = options.get("response-example-preference")
        self._generate_example_from_schema = options.get("generate-example-from-schema")

    def render_restructuredtext_markup(self, spec):
        """Spec render entry point."""
        yield from self.render_paths(spec)

    def render_paths(self, node):
        """Render OAS paths item."""

        for endpoint, pathitem in node.get("paths", {}).items():
            for method, operation in pathitem.items():
                operation.setdefault("parameters", [])
                parameters = [
                    parameter
                    for parameter in pathitem.get("parameters", [])
                    if (parameter["name"], parameter["in"])
                    not in [
                        (op_parameter["name"], op_parameter["in"])
                        for op_parameter in operation.get("parameters", [])
                    ]
                ]
                operation["parameters"] += parameters

                yield from self.render_operation(endpoint, method, operation)
                yield ""

    def render_operation(self, endpoint, method, operation):
        """Render OAS operation item."""

        yield f".. http:{method}:: {endpoint}"

        if operation.get("deprecated"):
            yield f"    :deprecated:"
        yield f""

        if operation.get("summary"):
            yield f"    **{operation['summary']}**"
            yield f""

        if operation.get("description"):
            yield from indented(
                self._convert_markup(operation["description"]).strip().splitlines()
            )
            yield f""

        yield from indented(self.render_parameters(operation.get("parameters", [])))
        yield from indented(self.render_responses(operation["responses"]))

    def render_parameters(self, parameters):
        """Render OAS operation's parameters."""

        for parameter in sorted(
            parameters,
            key=lambda p: self._request_parameters_order.index(p["in"].lower()),
        ):
            yield from self.render_parameter(parameter)

    def render_parameter(self, parameter):
        """Render OAS operation's parameter."""

        kinds = {"path": "param", "query": "queryparam", "header": "reqheader"}
        markers = []
        schema = parameter.get("schema", {})

        if "content" in parameter:
            # According to OpenAPI v3 spec, 'content' in this case may
            # have one and only one entry. Hence casting its values to
            # list is not expensive and should be acceptable.
            schema = list(parameter["content"].values())[0].get("schema", {})

        if parameter["in"] not in kinds:
            logger.warning(
                "OpenAPI spec contains parameter '%s' (in: '%s') that cannot "
                "be rendererd.",
                parameter["name"],
                parameter["in"],
            )
            return

        if schema.get("type"):
            type_ = schema["type"]
            if schema.get("format"):
                type_ = f"{type_}:{schema['format']}"
            markers.append(type_)

        if parameter.get("required"):
            markers.append("required")

        if parameter.get("deprecated"):
            markers.append("deprecated")

        yield f":{kinds[parameter['in']]} {parameter['name']}:"

        if parameter.get("description"):
            yield from indented(
                self._convert_markup(parameter["description"]).strip().splitlines()
            )

        if markers:
            markers = ", ".join(markers)
            yield f":{kinds[parameter['in']]}type {parameter['name']}: {markers}"

    def render_responses(self, responses):
        """Render OAS operation's responses."""

        for status_code, response in responses.items():
            yield from self.render_response(status_code, response)

    def render_response(self, status_code, response):
        """Render OAS operation's response."""

        yield f":statuscode {status_code}:"
        yield from indented(
            self._convert_markup(response["description"]).strip().splitlines()
        )

        if "content" in response:
            yield ""
            yield from indented(
                self.render_response_content(response["content"], status_code)
            )

        if "headers" in response:
            yield ""

            for header_name, header_value in response["headers"].items():
                # According to OpenAPI v3 specification, if a response header
                # is defined with the name 'Content-Type', it shall be ignored.
                if header_name.lower() == "content-type":
                    continue

                yield f":resheader {header_name}:"

                if header_value.get("description"):
                    yield from indented(
                        self._convert_markup(header_value["description"])
                        .strip()
                        .splitlines()
                    )

                markers = []
                schema = header_value.get("schema", {})
                if "content" in header_value:
                    # According to OpenAPI v3 spec, 'content' in this case may
                    # have one and only one entry. Hence casting its values to
                    # list is not expensive and should be acceptable.
                    schema = list(header_value["content"].values())[0].get("schema", {})

                if schema.get("type"):
                    type_ = schema["type"]
                    if schema.get("format"):
                        type_ = f"{type_}:{schema['format']}"
                    markers.append(type_)

                if header_value.get("required"):
                    markers.append("required")

                if header_value.get("deprecated"):
                    markers.append("deprecated")

                if markers:
                    markers = ", ".join(markers)
                    yield f":resheadertype {header_name}: {markers}"

    def render_response_content(self, media_type, status_code):
        # OpenAPI 3.0 spec may contain more than one response media type, and
        # each media type may contain more than one example. Rendering all
        # invariants normally is not an option because the result will be hard
        # to read and follow. The best option we can go with at this moment is
        # to render first found example of either response media type. Users
        # should control what to render by putting recommended example first in
        # the list.
        content_type, example = next(
            _iterexamples(
                media_type,
                self._response_example_preference,
                self._generate_example_from_schema,
            ),
            (None, None),
        )

        if content_type and example:
            example = example["value"]

            if not isinstance(example, str):
                example = json.dumps(example, indent=2)

            # According to OpenAPI v3 spec, status code may be a special value
            # - "default". It's not quite clear what to render in this case.
            # One possible option is to avoid rendering status code at all.
            # This option, however, suffers from broken code highlighting
            # because Pygments relies on the snippet to start with HTTP
            # protocol line. That said, probably the best we can do at the
            # moment is to render some generic status.
            if status_code == "default":
                status_code = "000"
                status_text = "Reason-Phrase"
            else:
                # According to OpenAPI v3 spec, status code may define a range
                # of response codes. Since we're talking about rendered example
                # here, we may show either code from range, but for the sake of
                # simplicity let's pick the first one.
                status_code = str(status_code).replace("XX", "00")
                status_text = http.client.responses.get(int(status_code), "-")

            yield f".. sourcecode:: http"
            yield f""
            yield f"   HTTP/1.1 {status_code} {status_text}"
            yield f"   Content-Type: {content_type}"
            yield f""
            yield from indented(example.splitlines())


def _generate_example_from_schema(schema):
    """
    Generates an example request/response body from the provided schema.

    >>> schema = {
    ...     "type": "object",
    ...     "required": ["id", "name"],
    ...     "properties": {
    ...         "id": {
    ...             "type": "integer",
    ...             "format": "int64"
    ...         },
    ...         "name": {
    ...             "type": "string",
    ...             "example": "John Smith"
    ...         },
    ...         "tag": {
    ...             "type": "string"
    ...         }
    ...     }
    ... }
    >>> example = _generate_example_from_schema(schema)
    >>> assert example == {
    ...     "id": 1,
    ...     "name": "John Smith",
    ...     "tag": "string"
    ... }
    """
    # If an example was provided then we use that
    if "example" in schema:
        return schema["example"]

    elif "oneOf" in schema:
        return _generate_example_from_schema(schema["oneOf"][0])

    elif "anyOf" in schema:
        return _generate_example_from_schema(schema["anyOf"][0])

    elif "allOf" in schema:
        # Combine schema examples
        example = {}
        for sub_schema in schema["allOf"]:
            example.update(_generate_example_from_schema(sub_schema))
        return example

    elif "enum" in schema:
        return schema["enum"][0]

    elif "type" not in schema:
        # Any type
        return _DEFAULT_EXAMPLES["integer"]

    elif schema["type"] == "object" or "properties" in schema:
        example = {}
        for prop, prop_schema in schema.get("properties", {}).items():
            example[prop] = _generate_example_from_schema(prop_schema)
        return example

    elif schema["type"] == "array":
        items = schema["items"]
        min_length = schema.get("minItems", 0)  # Good
        max_length = schema.get("maxItems", max(min_length, 2))
        assert min_length <= max_length
        # Try generate at least 2 example array items
        gen_length = min(2, max_length) if min_length <= 2 else min_length

        example_items = []
        if items == {}:
            # Any-type arrays
            example_items.extend(_DEFAULT_EXAMPLES.values())
        elif isinstance(items, dict) and "oneOf" in items:
            # Mixed-type arrays
            example_items.append(_DEFAULT_EXAMPLES[sorted(items["oneOf"])[0]])
        else:
            example_items.append(_generate_example_from_schema(items))

        # Generate array containing example_items and satisfying min_length and max_length
        return [example_items[i % len(example_items)] for i in range(gen_length)]

    elif schema["type"] == "string" and "format" in schema:
        return _DEFAULT_STRING_EXAMPLES.get(
            schema["format"], _DEFAULT_EXAMPLES["string"]
        )

    else:
        return _DEFAULT_EXAMPLES[schema["type"]]