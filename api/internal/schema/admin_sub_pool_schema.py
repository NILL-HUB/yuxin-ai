from flask_wtf import FlaskForm
from wtforms import BooleanField, FieldList, StringField
from wtforms.validators import AnyOf, DataRequired, Length, Optional

POOL_TYPES = ["agent", "tool"]


class CreateSubPoolDefinitionReq(FlaskForm):
    pool_type = StringField("pool_type", validators=[DataRequired(), AnyOf(POOL_TYPES)])
    name = StringField("name", validators=[DataRequired(), Length(min=1, max=64)])
    label = StringField("label", validators=[DataRequired(), Length(min=1, max=128)])
    description = StringField("description", validators=[Optional(), Length(max=500)])
    visible_to_user = BooleanField("visible_to_user", default=True)
    default_enabled = BooleanField("default_enabled", default=True)
    default_capabilities = FieldList(StringField("capability"))
    task_keywords = FieldList(StringField("keyword"))
    sort_order = StringField("sort_order", default="0")


class UpdateSubPoolDefinitionReq(FlaskForm):
    label = StringField("label", validators=[Optional(), Length(min=1, max=128)])
    description = StringField("description", validators=[Optional(), Length(max=500)])
    visible_to_user = BooleanField("visible_to_user")
    default_enabled = BooleanField("default_enabled")
    default_capabilities = FieldList(StringField("capability"))
    task_keywords = FieldList(StringField("keyword"))
    sort_order = StringField("sort_order")
    enabled = BooleanField("enabled")
