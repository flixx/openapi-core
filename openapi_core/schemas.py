"""OpenAPI core schemas module"""
import logging
from distutils.util import strtobool
from collections import defaultdict

from json import loads
from six import iteritems

from openapi_core.models import ModelFactory

log = logging.getLogger(__name__)

DEFAULT_CAST_CALLABLE_GETTER = {
    'integer': int,
    'number': float,
    'boolean': lambda x: bool(strtobool(x)),
}


class Schema(object):
    """Represents an OpenAPI Schema."""

    def __init__(
            self, schema_type, model=None, properties=None, items=None,
            spec_format=None, required=False):
        self.type = schema_type
        self.model = model
        self.properties = properties and dict(properties) or {}
        self.items = items
        self.format = spec_format
        self.required = required

    def __getitem__(self, name):
        return self.properties[name]

    def get_cast_mapping(self):
        mapping = DEFAULT_CAST_CALLABLE_GETTER.copy()
        mapping.update({
            'array': self._unmarshal_collection,
            'object': self._unmarshal_object,
        })

        return defaultdict(lambda: lambda x: x, mapping)

    def cast(self, value):
        """Cast value to schema type"""
        if value is None:
            return None

        cast_mapping = self.get_cast_mapping()

        if self.type in cast_mapping and value == '':
            return None

        cast_callable = cast_mapping[self.type]
        try:
            return cast_callable(value)
        except ValueError:
            log.warning(
                "Failed to cast value of %s to %s", value, self.type,
            )
            return value

    def unmarshal(self, value):
        """Unmarshal parameter from the value."""
        casted = self.cast(value)

        if casted is None and not self.required:
            return None

        return casted

    def _unmarshal_collection(self, value):
        return list(map(self.items.unmarshal, value))

    def _unmarshal_object(self, value):
        if isinstance(value, (str, bytes)):
            value = loads(value)

        properties = {}
        for prop_name, prop in iteritems(self.properties):
            prop_value = value.get(prop_name)
            properties[prop_name] = prop.unmarshal(prop_value)
        return ModelFactory().create(properties, name=self.model)


class PropertiesGenerator(object):

    def __init__(self, dereferencer):
        self.dereferencer = dereferencer

    def generate(self, properties):
        for property_name, schema_spec in iteritems(properties):
            schema = self._create_schema(schema_spec)
            yield property_name, schema

    def _create_schema(self, schema_spec):
        return SchemaFactory(self.dereferencer).create(schema_spec)


class SchemaFactory(object):

    def __init__(self, dereferencer):
        self.dereferencer = dereferencer

    def create(self, schema_spec):
        schema_deref = self.dereferencer.dereference(schema_spec)

        schema_type = schema_deref['type']
        model = schema_deref.get('x-model', None)
        required = schema_deref.get('required', False)
        properties_spec = schema_deref.get('properties', None)
        items_spec = schema_deref.get('items', None)

        properties = None
        if properties_spec:
            properties = self._generate_properties(properties_spec)

        items = None
        if items_spec:
            items = self._create_items(items_spec)

        return Schema(
            schema_type, model=model, properties=properties, items=items,
            required=required,
        )

    def _generate_properties(self, properties_spec):
        return PropertiesGenerator(self.dereferencer).generate(properties_spec)

    def _create_items(self, items_spec):
        return self.create(items_spec)


class SchemaRegistry(SchemaFactory):

    def __init__(self, dereferencer):
        super(SchemaRegistry, self).__init__(dereferencer)
        self._schemas = {}

    def get_or_create(self, schema_spec):
        schema_deref = self.dereferencer.dereference(schema_spec)
        model = schema_deref.get('x-model', None)

        if model and model in self._schemas:
            return self._schemas[model], False

        return self.create(schema_deref), True

    def _create_items(self, items_spec):
        schema, _ = self.get_or_create(items_spec)
        return schema


class SchemasGenerator(object):

    def __init__(self, dereferencer):
        self.dereferencer = dereferencer

    def generate(self, schemas_spec):
        schemas_deref = self.dereferencer.dereference(schemas_spec)

        for schema_name, schema_spec in iteritems(schemas_deref):
            schema = self._create_schema(schema_spec)
            yield schema_name, schema

    def _create_schema(self, schema_spec):
        schema, _ = SchemaRegistry(self.dereferencer).get_or_create(
            schema_spec)
        return schema