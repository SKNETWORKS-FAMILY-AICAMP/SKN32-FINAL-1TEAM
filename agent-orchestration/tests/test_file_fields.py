"""계약 파일 칸의 참조형 교체 (결정 0023 · spec 4.5).

- 스텁이 파일을 tools.files(G-04는 파일 창구 인자)로 넣고 참조를 싣는다 — 진입 파일 · 인포그래픽 · 안내 문서 · 계획서 파일
- M-2 감싸기(인포그래픽 그림 참조 → 진입 파일, 자산 없음), M-3 안내 문서 기입, T-C4 최종 묶음 참조 목록
- 진입 파일 없음(entryFile 비움)과 이전 원문 참조(previous_source_file)를 비우는 경우
- 웹 결과 조회(outputs)의 새 칸 모양 — 참조만 나가고 파일 내용은 없다
흐름 테스트는 메모리 · SQLite 두 저장소에서 돈다 (clock 픽스처).
"""
from __future__ import annotations

import hashlib
import json

from conftest import executed, make_app, to_screen8, to_screen9
from flow_helpers import ctx_of, pid, records_of_task, rework, run_review

from sbrain.agents.stubs import StubScenario, bind_stubs
from sbrain.contracts import tasks as c
from sbrain.flow.catalog import build_registry
from sbrain.models import FileRef, Infographic, ItemSpec, Prototype

FEATURES = ["회원 등록·조회", "수업 예약"]   # 스텁 T-C1의 핵심 기능 = featureList
REF_KEYS = {"key", "name", "mediaType", "size", "sha256"}


def fref(name: str, media_type: str) -> FileRef:
    return FileRef(key=f"run-x/e/u/{name}", name=name, media_type=media_type, size=1, sha256="0" * 64)


def check_stored(app, rid: str, ref: FileRef) -> bytes:
    """참조가 이 실행 건 것이고 저장소의 내용 · 해시 · 크기와 맞는지 확인하고 내용을 돌려준다."""
    data = app.engine.files.read(ref.key)
    assert ref.run_id == rid and ref.key.endswith("/" + ref.name)
    assert (ref.size, ref.sha256) == (len(data), hashlib.sha256(data).hexdigest())
    return data


def no_entry_file(app) -> None:
    """T-B1이 진입 파일 없이 끝난다(entryFile 비움) — 진입 파일 없음."""
    base = app.registry.get("T-B1").fn

    def fn(inp, tools):
        out = base(inp, tools)
        return out.model_copy(update={"entry_file": None,
                                      "prototype": out.prototype.model_copy(update={"entry_file": None})})
    app.registry.bind("T-B1", fn)


def capture(app, task_id: str) -> list:
    seen, base = [], app.registry.get(task_id).fn

    def fn(inp, tools):
        seen.append(inp.rework_input)
        return base(inp, tools)
    app.registry.bind(task_id, fn)
    return seen


# ── 계약 · 등록부 ────────────────────────────────────────
def test_old_fields_are_gone_and_new_fields_shape():
    assert set(Prototype.model_fields) == {"entry_file", "kind", "asset_files", "readme_file", "implemented_features"}
    assert set(Infographic.model_fields) == {"image_file", "format", "alt_text"}
    assert Prototype.model_fields["entry_file"].default is None                 # 비면 진입 파일 없음
    assert Prototype.model_fields["asset_files"].is_required()
    assert c.G04Out.model_fields["readme_file"].is_required()
    assert c.TB1Out.model_fields["entry_file"].default is None
    p = Prototype(kind="html", asset_files=[], implemented_features=[])
    assert p.entry_file is None and p.readme_file is None
    assert set(p.dump()) == {"entryFile", "kind", "assetFiles", "readmeFile", "implementedFeatures"}


def test_catalog_wires_file_keys_and_g04_writes_files():
    r = build_registry()
    tb1, g04, m3 = r.get("T-B1"), r.get("G-04"), r.get("M-3")
    assert tb1.outputs["entry_file"] == "entryFile"
    assert g04.outputs["readme_file"] == "readmeFile" and g04.primary_output == "readme_file"
    assert g04.writes_files and g04.kind == "rule"
    assert (m3.inputs["readme_file"].kind, m3.inputs["readme_file"].key) == ("art", "readmeFile")
    assert not any(s.writes_files for s in r.specs() if s.task_id != "G-04")


# ── 스텁 단위 ────────────────────────────────────────────
def stub_fn(task_id: str):
    r = build_registry()
    bind_stubs(r, StubScenario())
    return r.get(task_id).fn


def test_stub_m2_wraps_infographic_as_entry_file_without_opening_it():
    image = fref("onepage.svg", "image/svg+xml")
    item = ItemSpec(item_name="i", one_line_summary="s", target_customer="t", core_features=FEATURES,
                    category="원페이지", keywords=[])
    out = stub_fn("M-2")(c.M2In(infographic=Infographic(image_file=image, format="svg", alt_text="a"),
                                item_spec=item, feature_list=FEATURES))
    proto = out.prototype
    assert (proto.kind, proto.entry_file, proto.asset_files, proto.readme_file) == ("svg-onepage", image, [], None)
    assert proto.implemented_features == FEATURES


def test_stub_m3_sets_readme_file():
    readme = fref("README.md", "text/markdown")
    proto = Prototype(entry_file=fref("index.html", "text/html"), kind="html", asset_files=[],
                      implemented_features=[])
    out = stub_fn("M-3")(c.M3In(prototype=proto, readme_file=readme))
    assert out.prototype.readme_file == readme and out.prototype.entry_file == proto.entry_file


# ── 흐름 ────────────────────────────────────────────────
def test_web_flow_puts_stub_files_and_carries_refs(clock):
    app = make_app(clock)
    rid = to_screen9(app)
    run_review(app, rid)
    assert app.store.load_run(rid).state.progress == "완료"
    ctx = ctx_of(app, rid)
    proto, info = ctx.get("prototype"), ctx.get("infographic")
    assert (proto.entry_file.name, proto.entry_file.media_type) == ("index.html", "text/html")
    assert proto.entry_file == ctx.get("entryFile") and proto.asset_files == []
    assert (info.image_file.name, info.image_file.media_type) == ("infographic.png", "image/png")
    assert proto.readme_file == ctx.get("readmeFile") and proto.readme_file.name == "README.md"
    assert all(ch.image_file is None for ch in ctx.get("planDoc").charts)         # 차트 그림은 비운다
    for ref in (proto.entry_file, info.image_file, proto.readme_file):
        check_stored(app, rid, ref)
    d = ctx.get("deliverable")
    assert (d.plan_doc_file.name, d.plan_doc_file.media_type) == (
        "plan.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    check_stored(app, rid, d.plan_doc_file)
    assert d.prototype_files == [proto.entry_file, proto.readme_file]           # 진입 파일 · 안내 문서 · 자산
    assert d.infographic_file == info.image_file


def test_g04_puts_readme_through_file_window_in_its_own_record(clock):
    app = make_app(clock)
    rid = to_screen8(app)
    [g04] = records_of_task(app, rid, "G-04")
    logs = [x for x in app.store.call_logs(rid) if x.execution_id == g04.execution_id]
    assert [(x.call_type, x.purpose, x.final_outcome) for x in logs] == [("file", "put", "성공")]
    readme = ctx_of(app, rid).get("readmeFile")
    assert check_stored(app, rid, readme).decode().startswith("# 실행 · 열람 안내")
    # 호출 기록에 파일 이름 · 키 · 내용이 없다
    dumped = json.dumps([x.dump() for x in app.store.call_logs(rid)], ensure_ascii=False)
    assert readme.key not in dumped and "README.md" not in dumped and "열람 안내" not in dumped


def test_onepage_m2_wraps_tb2_svg_into_prototype(clock):
    app = make_app(clock, StubScenario(category="원페이지"))
    rid = to_screen9(app)
    run_review(app, rid)
    ex = executed(app, rid)
    assert "T-B1" not in ex and "M-2" in ex
    ctx = ctx_of(app, rid)
    info, proto = ctx.get("infographic"), ctx.get("prototype")
    assert (info.format, info.image_file.name, info.image_file.media_type) == ("svg", "onepage.svg", "image/svg+xml")
    assert proto.entry_file == info.image_file and proto.asset_files == []
    assert check_stored(app, rid, proto.entry_file).startswith(b"<svg")
    d = ctx.get("deliverable")
    assert d.prototype_files == [proto.entry_file, proto.readme_file] and d.infographic_file == info.image_file


def test_no_entry_file_flows_to_the_end(clock):
    app = make_app(clock)
    no_entry_file(app)
    rid = to_screen9(app)
    run_review(app, rid)
    assert app.store.load_run(rid).state.progress == "완료"
    ctx = ctx_of(app, rid)
    proto = ctx.get("prototype")
    assert proto.entry_file is None and ctx.get("entryFile") is None and proto.readme_file is not None
    assert ctx.get("deliverable").prototype_files == [proto.readme_file]       # 진입 파일 없음 — 안내 문서만


def test_previous_source_file_empty_when_no_entry_file(clock):
    # 재수행 · 사용자 재작성 대상 모두 — 진입 파일이 없으면 이전 원문 참조도 비운다
    app = make_app(clock, StubScenario(art_scores=[(12.0, 7.0)], check_fail_times={"T-B1": 1}))
    no_entry_file(app)
    seen = capture(app, "T-B1")
    rid = to_screen8(app)
    first, redo = seen
    assert first is None and redo.mode == "재수행" and redo.previous_source_file is None
    rework(app, clock, rid, "실행 파일")
    target = seen[-1]
    assert target.mode == "재작성" and target.previous_source_file is None


def test_previous_source_file_is_entry_file_ref(clock):
    # 재수행 — 방금 실행이 만든 진입 파일 참조, 사용자 재작성 대상 — 재작성 직전 prototype의 진입 파일 참조
    app = make_app(clock, StubScenario(art_scores=[(12.0, 7.0)], check_fail_times={"T-B1": 1}))
    seen = capture(app, "T-B1")
    rid = to_screen8(app)
    [first_rec, redo_rec] = records_of_task(app, rid, "T-B1")
    ctx = ctx_of(app, rid)
    first_proto = ctx.get_ref(first_rec.result_ref)
    assert seen[1].previous_source_file == first_proto.entry_file
    before = ctx.get("prototype").entry_file
    rework(app, clock, rid, "실행 파일")
    assert seen[-1].previous_source_file == before and before.run_id == rid


def test_outputs_carry_refs_without_file_content(clock):
    app = make_app(clock)
    rid = to_screen9(app)
    run_review(app, rid)
    out = app.orchestrator.outputs(pid(app, rid)).dump()
    proto, info, d = out["prototype"], out["infographic"], out["deliverable"]
    assert set(proto) == {"entryFile", "kind", "assetFiles", "readmeFile", "implementedFeatures"}
    assert set(proto["entryFile"]) == REF_KEYS and set(proto["readmeFile"]) == REF_KEYS
    assert proto["entryFile"]["name"] == "index.html" and proto["assetFiles"] == []
    assert set(info) == {"imageFile", "format", "altText"} and set(info["imageFile"]) == REF_KEYS
    assert set(d) == {"planDocFile", "prototypeFiles", "infographicFile", "scoreReport", "proofreadLog",
                      "disclaimer", "prototypeNotice", "scoreNotice", "submissionNotice"}
    assert [f["name"] for f in d["prototypeFiles"]] == ["index.html", "README.md"]
    text = json.dumps(out, ensure_ascii=False)
    assert "스텁 프로토타입" not in text and "열람 안내" not in text           # 파일 내용은 들어 있지 않다
