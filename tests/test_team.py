import pytest


@pytest.fixture
def team_file(tmp_path):
    return str(tmp_path / "team.json")


@pytest.fixture
def t(team_file, monkeypatch):
    import team
    monkeypatch.setattr(team, "TEAM_FILE", team_file)
    return team


def test_add_and_get_member(t):
    t.add_member("Иван", "asana_gid_123", "@ivan_tg")
    member = t.get_member("Иван")
    assert member is not None
    assert member["asana_gid"] == "asana_gid_123"
    assert member["telegram_username"] == "@ivan_tg"
    assert member["telegram_id"] is None


def test_remove_member(t):
    t.add_member("Петр", "asana_gid_456", "@petr_tg")
    assert t.remove_member("Петр") is True
    assert t.get_member("Петр") is None


def test_remove_nonexistent_returns_false(t):
    assert t.remove_member("Несуществующий") is False


def test_set_and_get_telegram_id(t):
    t.add_member("Анна", "asana_gid_789", "@anna_tg")
    result = t.set_telegram_id("Анна", 999888)
    assert result is True
    assert t.get_member("Анна")["telegram_id"] == 999888


def test_set_telegram_id_nonexistent_returns_false(t):
    assert t.set_telegram_id("Несуществующий", 12345) is False


def test_get_member_by_telegram_id(t):
    t.add_member("Мария", "asana_gid_111", "@maria_tg")
    t.set_telegram_id("Мария", 111222)
    member = t.get_member_by_telegram_id(111222)
    assert member is not None
    assert member["name"] == "Мария"


def test_get_member_by_telegram_id_not_found(t):
    assert t.get_member_by_telegram_id(99999) is None


def test_get_member_by_asana_gid(t):
    t.add_member("Сергей", "asana_gid_333", "@sergey_tg")
    member = t.get_member_by_asana_gid("asana_gid_333")
    assert member is not None
    assert member["name"] == "Сергей"


def test_get_member_by_asana_gid_not_found(t):
    assert t.get_member_by_asana_gid("nonexistent") is None


def test_is_allowed_admin(t):
    assert t.is_allowed(12345, admin_id=12345) is True


def test_is_allowed_team_member(t):
    t.add_member("Дима", "asana_gid_222", "@dima_tg")
    t.set_telegram_id("Дима", 77777)
    assert t.is_allowed(77777, admin_id=12345) is True


def test_is_allowed_stranger(t):
    assert t.is_allowed(99999, admin_id=12345) is False


def test_list_members(t):
    t.add_member("Один", "gid1", "@one")
    t.add_member("Два", "gid2", "@two")
    members = t.list_members()
    names = [m["name"] for m in members]
    assert "Один" in names
    assert "Два" in names
