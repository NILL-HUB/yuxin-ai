from wtforms import Form, StringField
from wtforms.validators import DataRequired, Length, Optional


class SuperiorBindReq(Form):
    inviter_id = StringField("inviter_id", validators=[Optional(), Length(max=64)])