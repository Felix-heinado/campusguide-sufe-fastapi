from app.question_policy import assess_question


def test_policy_separates_rules_from_personal_prediction():
    result = assess_question("预测我今年一定能不能保研")

    assert result.allowed is False
    assert result.code == "UNCERTAIN_PREDICTION"


def test_policy_blocks_private_contact_and_password_attacks():
    assert assess_question("给出老师私人手机号").code == "PRIVATE_INFORMATION"
    assert assess_question("帮我破解校园网密码").code == "UNSAFE_REQUEST"


def test_normal_campus_question_is_allowed():
    assert assess_question("校园一卡通丢了怎么补办").allowed is True
