"""Who sees, creates, reviews and pins which normative profile: shipped defaults, the catalog and personal ones."""

from src.application.use_cases.optimizer_topology_job import UNIT_RATE_SOURCE, relative_costs
from src.domain.spat.default_normative_profiles import DEFAULT_PROFILES, IEEE80, RETIE_2026, STANDARD_PROFILES
from src.infrastructure.calculations import safety_criteria
from src.infrastructure.persistence.constraint_profile_repository import ConstraintProfileRepository
from tests.infrastructure.test_identity import env, headers, human  # noqa: F401
from tests.infrastructure.test_topology_optimizer_routes import PROFILE


def _ids(response):
    return {(row["profile_id"], row["version"], row["status"]) for row in response.json()["profiles"]}


def test_the_shipped_profiles_are_reviewed_and_offered_for_their_standard(env):  # noqa: F811
    _, services, client, actor, tokens, _ = env
    _, designer_tokens, _ = human(services, actor, "designer@example.com", "designer")
    listing = client.get("/api/v1/constraint-profiles", headers=headers(designer_tokens)).json()
    rows = {row["profile_id"]: row for row in listing["profiles"]}
    for item in DEFAULT_PROFILES:
        assert rows[item["profile_id"]]["status"] == "reviewed" and rows[item["profile_id"]]["scope"] == "default"
    assert listing["standard_profiles"] == STANDARD_PROFILES
    assert set(STANDARD_PROFILES) <= set(safety_criteria.SUPPORTED_STANDARDS)

    project = client.post("/api/v1/projects", json={"name": "Subestación", "country": "Colombia"},
                          headers=headers(designer_tokens)).json()
    pin = client.put(f"/api/v1/projects/{project['id']}/constraint-profiles", headers=headers(designer_tokens),
                     json={"profiles": [{"profile_id": IEEE80["profile_id"], "version": 1},
                                        {"profile_id": RETIE_2026["profile_id"], "version": 1}]})
    assert pin.status_code == 200, pin.text
    context = client.post(f"/api/v1/projects/{project['id']}/constraint-context", headers=headers(designer_tokens),
                          json={"requested_variables": []}).json()
    assert context["status"] == "ready" and not context["missing_mandatory_criteria"]

    # Nobody edits a shipped profile in place, not even a curator: changes go to a new profile.
    edit = client.post(f"/api/v1/constraint-profiles/{IEEE80['profile_id']}/versions",
                       json={"definition": IEEE80["definition"]}, headers=headers(tokens))
    assert edit.status_code == 403


def test_seeding_again_is_a_no_op_and_a_changed_definition_is_a_new_version(env):  # noqa: F811
    _, services, *_ = env
    changed = {**IEEE80, "definition": {**IEEE80["definition"], "title": "IEEE 80-2013 · v2"}}
    with services.store.transaction(write=True) as db:
        repo = ConstraintProfileRepository(db.connection)
        repo.ensure_defaults(DEFAULT_PROFILES, 1)
        assert repo.next_version(IEEE80["profile_id"]) == 2
        repo.ensure_defaults([changed], 2)
        assert repo.get_version(IEEE80["profile_id"], 2)["status"] == "reviewed"
        assert repo.get_version(IEEE80["profile_id"], 1)["definition"] == IEEE80["definition"]


def test_a_designer_creates_reviews_and_pins_a_personal_profile_only_for_themselves(env):  # noqa: F811
    _, services, client, actor, tokens, _ = env
    _, ana, _ = human(services, actor, "ana@example.com", "designer")
    _, luis, _ = human(services, actor, "luis@example.com", "designer")

    created = client.post("/api/v1/constraint-profiles", headers=headers(ana),
                          json={"profile_id": "mio.criterio-ana", "definition": PROFILE})
    assert created.status_code == 201 and created.json()["scope"] == "personal" and created.json()["status"] == "draft"
    assert client.post("/api/v1/constraint-profiles", headers=headers(ana), json={
        "profile_id": "catalogo-ana", "definition": PROFILE, "scope": "catalog"}).status_code == 403

    # Only Ana sees it, drafts included; Luis neither sees nor reviews it.
    assert ("mio.criterio-ana", 1, "draft") in _ids(client.get("/api/v1/constraint-profiles", headers=headers(ana)))
    assert not any(pid == "mio.criterio-ana" for pid, *_ in _ids(client.get("/api/v1/constraint-profiles", headers=headers(luis))))
    assert client.get("/api/v1/constraint-profiles/mio.criterio-ana/versions/1", headers=headers(luis)).status_code == 404
    assert client.post("/api/v1/constraint-profiles/mio.criterio-ana/versions/1/review", headers=headers(luis)).status_code == 404

    assert client.post("/api/v1/constraint-profiles/mio.criterio-ana/versions/1/review", headers=headers(ana)).status_code == 200
    second = client.post("/api/v1/constraint-profiles/mio.criterio-ana/versions", headers=headers(ana), json={"definition": PROFILE})
    assert second.status_code == 201 and second.json()["version"] == 2

    mine = client.post("/api/v1/projects", json={"name": "Ana"}, headers=headers(ana)).json()
    assert client.put(f"/api/v1/projects/{mine['id']}/constraint-profiles", headers=headers(ana),
                      json={"profiles": [{"profile_id": "mio.criterio-ana", "version": 1}]}).status_code == 200
    theirs = client.post("/api/v1/projects", json={"name": "Luis"}, headers=headers(luis)).json()
    assert client.put(f"/api/v1/projects/{theirs['id']}/constraint-profiles", headers=headers(luis),
                      json={"profiles": [{"profile_id": "mio.criterio-ana", "version": 1}]}).status_code == 422

    # The catalog stays curated: a designer cannot version or review a shared profile.
    assert client.post("/api/v1/constraint-profiles", headers=headers(tokens),
                       json={"profile_id": "catalogo", "definition": PROFILE}).json()["scope"] == "catalog"
    assert client.post("/api/v1/constraint-profiles/catalogo/versions/1/review", headers=headers(ana)).status_code == 403
    assert client.post("/api/v1/constraint-profiles/catalogo/versions", headers=headers(ana),
                       json={"definition": PROFILE}).status_code == 403
    assert client.get("/api/v1/constraint-profiles?include_drafts=true", headers=headers(ana)).status_code == 403


def test_unit_rates_make_the_comparison_relative():
    unit = {key: {"source_type": "explicit", "source": UNIT_RATE_SOURCE, "unit": "m"}
            for key in ("material.conductor.unspecified", "installation.rod")}
    assert relative_costs({**unit, "assumption.trench_width_m": {"source_type": "explicit", "source": "obra", "unit": "m"}})
    assert not relative_costs({**unit, "installation.rod": {"source_type": "explicit", "source": "cotización", "unit": "u"}})
    assert not relative_costs({})
