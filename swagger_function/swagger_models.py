from flask_restx import Namespace, fields

# -------------------------------------------------------
# Create namespace
# -------------------------------------------------------
swagger_ns = Namespace(
    "Swagger",
    description="This is Akshya's namespace"
)

# -------------------------------------------------------
# Nested model
# -------------------------------------------------------
nested_model = swagger_ns.model(
    "SwaggerNestedModel",
    {
        "triggerLine": fields.String(description="Line to be triggered", required=True),
        "contains": fields.Boolean(description="Check if text contains keyword", required=True),
        "length": fields.Integer(description="Max length of keyword"),
        "value": fields.String(description="Keyword value", required=True),
    },
)

# -------------------------------------------------------
# Parent model
# -------------------------------------------------------
swagger_input_model = swagger_ns.model(
    "SwaggerModel",
    {
        "name": fields.String(description="User name", required=True),
        "age": fields.Integer(description="Age of user", required=True),
        "data": fields.String(description="Input data", required=True),
        "status": fields.Boolean(description="Provider status"),
        "nestedData": fields.List(
            fields.Nested(nested_model),
            description="List of keyword objects",
            required=True,
        ),
    },
)

# -------------------------------------------------------
# Register models to API from app.py
# (Do NOT recreate models!)
# -------------------------------------------------------
def register_models(api):
    """
    Ensures namespace models are attached to the main API.
    """
    api.add_namespace(swagger_ns)
    return swagger_input_model
