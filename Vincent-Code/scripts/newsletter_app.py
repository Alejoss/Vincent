"""
Newsletter UI — escribir, previsualizar y enviar (SMTP2GO).

  streamlit run scripts/newsletter_app.py
  scripts\\run_newsletter_app.bat
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPTS_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env", override=True)

import streamlit as st

from src.newsletter.config import (
    PREVIEW_DIR,
    activity_url,
    list_markdown_files,
    list_segments,
    load_config,
    save_settings,
    test_connection,
    validate_config,
)
from src.newsletter.send_client import send_campaign, send_test
from src.newsletter.renderer import (
    compose_markdown_file,
    render_markdown,
    render_markdown_file,
    save_preview_html,
)
from src.campaigns.editorial import (
    CHANNEL_FILES,
    list_campaign_choices,
    list_newsletter_choices,
    list_newsletter_files,
    list_post_files,
)
from src.editorial.loaders import _strip_frontmatter, read_campaign_doc
from src.editorial.paths import ALL_CHANNELS
from src.editorial.pipeline import generate_all, generate_channels, generate_essay, generate_outline
from src.llm_client import build_editorial_llm_config
from src.campaigns.registry import (
    channel_sends_for_editorial,
    list_editorial_campaigns_db,
    record_channel_send,
    sync_editorial_campaigns,
)
from src.newsletter.campaign_log import record_campaign_send
from src.newsletter.send_log import append_send_log, read_send_log
from src.newsletter.subscribers import (
    default_subscribers_path,
    list_segment_counts,
    load_all_subscribers,
    load_segment,
    subscriber_source_label,
)

st.set_page_config(
    page_title="Newsletter — Academia Blockchain",
    page_icon="📧",
    layout="wide",
)

TAG_SUGGESTIONS = ["club-de-lectura", "noticias", "anuncios", "newsletter"]


def _init_state() -> None:
    defaults = {
        "md_text": "",
        "md_path": None,
        "save_filename": "borrador.md",
        "subject": "",
        "preview_text": "",
        "tag": "club-de-lectura",
        "segment": "test",
        "test_email": "",
        "editorial_slug": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _load_file_into_state(path: Path, editorial_slug: str = "") -> None:
    rendered = render_markdown_file(path)
    st.session_state.md_text = path.read_text(encoding="utf-8")
    st.session_state.md_path = str(path)
    st.session_state.save_filename = path.name
    st.session_state.editorial_slug = editorial_slug
    st.session_state.subject = rendered.subject
    st.session_state.preview_text = rendered.preview_text
    st.session_state.tag = rendered.tag
    st.session_state.segment = rendered.segment


def _load_editorial_into_state(slug: str, newsletter_rel: str | None = None) -> None:
    from src.campaigns.editorial import get_campaign, resolve_newsletter_path

    camp = get_campaign(slug)
    path = resolve_newsletter_path(camp, newsletter_rel)
    _load_file_into_state(path, editorial_slug=camp.slug)


def _source_label() -> str:
    if st.session_state.md_path:
        return Path(st.session_state.md_path).name
    return "sin archivo (solo memoria del editor)"


def _current_rendered():
    return render_markdown(
        st.session_state.md_text,
        subject=st.session_state.subject,
        preview_text=st.session_state.preview_text,
        tag=st.session_state.tag,
        segment=st.session_state.segment,
        md_path=Path(st.session_state.md_path) if st.session_state.md_path else None,
    )


def page_compose() -> None:
    st.header("Componer newsletter")
    config = load_config()
    st.caption(
        "Carga una **campaña editorial** (`Campaigns/`) o un archivo suelto. "
        "Edita → guarda → vista previa → enviar."
    )

    col_left, col_right = st.columns([1, 1])

    with col_left:
        st.subheader("Campaña editorial")
        editorial_choices = list_campaign_choices()
        editorial_options = ["— Ninguna —"] + [label for _, label in editorial_choices]
        editorial_slugs = [""] + [slug for slug, _ in editorial_choices]
        idx = 0
        if st.session_state.editorial_slug:
            for i, slug in enumerate(editorial_slugs):
                if slug == st.session_state.editorial_slug:
                    idx = i
                    break
        selected_label = st.selectbox("Abrir campaña", editorial_options, index=idx)
        selected_idx = editorial_options.index(selected_label)
        selected_slug = editorial_slugs[selected_idx]
        newsletter_rel = ""
        if selected_slug:
            from src.campaigns.editorial import get_campaign, list_newsletter_choices

            nl_choices = list_newsletter_choices(get_campaign(selected_slug))
            if nl_choices:
                nl_options = [label for _, label in nl_choices]
                nl_paths = [rel for rel, _ in nl_choices]
                newsletter_rel = st.selectbox("Newsletter de la campaña", nl_options)
                newsletter_rel = nl_paths[nl_options.index(newsletter_rel)]
        if selected_slug and st.button("Cargar campaña", type="primary"):
            _load_editorial_into_state(selected_slug, newsletter_rel or None)
            st.success(f"Cargada: {selected_slug}")

        st.subheader("Archivo suelto (legacy)")
        md_files = list_markdown_files(config.md_dir)
        options = ["— Nuevo / pegar texto —"] + [f.name for f in md_files]
        selected = st.selectbox("Abrir desde newsletters/", options, key="md_select")

        if selected != options[0]:
            path = config.md_dir / selected
            if st.button("Cargar archivo"):
                _load_file_into_state(path)
                st.session_state.editorial_slug = ""
                st.success(f"Cargado: {selected}")

        if st.session_state.editorial_slug:
            st.caption(f"Campaña activa: `{st.session_state.editorial_slug}`")

        st.session_state.subject = st.text_input("Asunto", st.session_state.subject)
        st.session_state.preview_text = st.text_input(
            "Preview text (preheader)",
            st.session_state.preview_text,
            help="Texto breve visible en la bandeja de entrada",
        )

        tag_options = sorted(set(TAG_SUGGESTIONS + [st.session_state.tag]))
        if st.session_state.tag and st.session_state.tag not in tag_options:
            tag_options.append(st.session_state.tag)
        st.session_state.tag = st.selectbox(
            "Tag",
            tag_options,
            index=tag_options.index(st.session_state.tag) if st.session_state.tag in tag_options else 0,
        )
        custom_tag = st.text_input("O escribe un tag nuevo", "")
        if custom_tag.strip():
            st.session_state.tag = custom_tag.strip()

        segments = list_segments() or ["test"]
        if st.session_state.segment not in segments:
            segments = segments + [st.session_state.segment]
        st.session_state.segment = st.selectbox(
            "Segmento por defecto",
            segments,
            index=segments.index(st.session_state.segment),
        )

        counts = list_segment_counts()
        if counts:
            st.caption("Destinatarios activos: " + ", ".join(f"{k} ({v})" for k, v in counts.items()))
        st.caption(f"Lista: `{subscriber_source_label()}`")

    with col_right:
        st.subheader("Contenido (Markdown)")
        st.session_state.md_text = st.text_area(
            "Cuerpo del email",
            st.session_state.md_text,
            height=420,
            label_visibility="collapsed",
        )

        save_col1, save_col2 = st.columns(2)
        with save_col1:
            st.session_state.save_filename = st.text_input(
                "Guardar como",
                value=st.session_state.save_filename,
            )
        with save_col2:
            st.write("")
            if st.button("Guardar en Obsidian"):
                composed = compose_markdown_file(
                    st.session_state.md_text,
                    subject=st.session_state.subject,
                    preview_text=st.session_state.preview_text,
                    tag=st.session_state.tag,
                    segment=st.session_state.segment,
                )
                if st.session_state.editorial_slug:
                    from src.campaigns.editorial import get_campaign

                    if st.session_state.md_path:
                        out = Path(st.session_state.md_path)
                    else:
                        out = get_campaign(st.session_state.editorial_slug).newsletter_path
                else:
                    config.md_dir.mkdir(parents=True, exist_ok=True)
                    name = st.session_state.save_filename
                    name = name if name.endswith(".md") else f"{name}.md"
                    out = config.md_dir / name
                out.write_text(composed, encoding="utf-8")
                st.session_state.md_text = composed
                st.session_state.md_path = str(out)
                st.session_state.save_filename = out.name
                st.success(f"Guardado: {out}")


def page_preview() -> None:
    st.header("Vista previa")
    if not st.session_state.md_text.strip():
        st.info("Escribe o carga un newsletter en la pestaña Componer.")
        return

    rendered = _current_rendered()
    tab_html, tab_text, tab_src = st.tabs(["HTML", "Texto plano", "Código HTML"])

    with tab_html:
        st.components.v1.html(rendered.preview_html_body, height=640, scrolling=True)
        if rendered.attachments:
            st.caption(
                f"Vista previa del navegador. Al enviar, {len(rendered.attachments)} imagen(es) "
                "se adjuntan inline en el correo (CID)."
            )

    with tab_text:
        st.text(rendered.text_body)

    with tab_src:
        st.code(rendered.email_html_body, language="html")

    if st.button("Exportar preview a archivo"):
        path = save_preview_html(rendered, PREVIEW_DIR)
        st.success(f"Guardado: {path}")


def page_send() -> None:
    st.header("Enviar")
    config = load_config()
    errors = validate_config(config)
    if errors:
        st.error("Configuración incompleta:\n" + "\n".join(f"- {e}" for e in errors))
        return

    if not st.session_state.md_text.strip():
        st.info("Primero compón el newsletter.")
        return

    rendered = _current_rendered()
    if st.session_state.editorial_slug:
        st.info(f"Campaña editorial: `{st.session_state.editorial_slug}` · archivo: `{_source_label()}`")
    else:
        st.info(f"Se enviará el contenido actual del editor · archivo: `{_source_label()}`")
    st.markdown(f"**Asunto:** {rendered.subject}")
    st.markdown(f"**Tag:** `{rendered.tag}` · **Segmento:** `{rendered.segment}`")

    st.divider()
    st.subheader("Correo de prueba")
    test_to = st.text_input("Enviar prueba a", value=config.test_email or st.session_state.test_email)
    if st.button("Enviar prueba", type="secondary"):
        result = send_test(config, rendered, test_to)
        append_send_log(rendered, result, send_type="test", to_email=test_to)
        if result.ok:
            st.success(f"Prueba enviada a {test_to}")
        else:
            st.error(result.error or "Error desconocido")

    st.divider()
    st.subheader("Campaña")
    segment = st.selectbox(
        "Segmento",
        list_segments() or [rendered.segment],
        index=0,
    )
    try:
        subscribers = load_segment(segment)
        st.write(f"**{len(subscribers)}** destinatarios en `{segment}`")
    except FileNotFoundError as exc:
        st.warning(str(exc))
        subscribers = []

    confirm = st.checkbox("Confirmo que revisé la vista previa y envié una prueba")
    if st.button("Enviar campaña", type="primary", disabled=not confirm or not subscribers):
        sync_editorial_campaigns()
        result = send_campaign(config, rendered, subscribers)
        append_send_log(rendered, result, send_type="campaign", segment=segment)
        editorial_slug = st.session_state.editorial_slug or None
        if result.ok:
            send_id = record_campaign_send(
                rendered,
                result,
                subscribers,
                segment=segment,
                editorial_slug=editorial_slug,
            )
            if editorial_slug:
                record_channel_send(
                    editorial_slug=editorial_slug,
                    channel="newsletter",
                    newsletter_send_id=send_id,
                    ok=True,
                    method=result.method,
                    external_id=result.bulk_id,
                )
        if result.ok:
            st.success(
                f"Enviado a {result.recipient_count} destinatarios vía `{result.method}`."
            )
            st.link_button(
                "Ver estadísticas (SMTP2GO)",
                activity_url(rendered.tag),
            )
        else:
            st.error(result.error or "Error al enviar")


def page_editorial() -> None:
    st.header("Campañas editoriales")
    sync_editorial_campaigns()

    db_rows = list_editorial_campaigns_db()
    if not db_rows:
        st.info("No hay campañas. Crea una en `Cerebro-Vincent/Campaigns/` o usa `scripts/campaign_new.py`.")
        return

    for row in db_rows:
        with st.expander(f"{row['title']} — `{row['slug']}` [{row['status']}]"):
            st.write(f"Tag: `{row.get('email_tag') or row.get('postmark_tag')}` · Segmento: `{row['newsletter_segment']}`")
            st.write(f"Landing: {row['landing_page']}")
            sends = channel_sends_for_editorial(row["slug"])
            if sends:
                st.subheader("Envíos por canal")
                st.dataframe(sends, use_container_width=True)
            else:
                st.caption("Sin envíos registrados en SQLite.")


def page_generate() -> None:
    st.header("Generar contenido (IA)")
    st.caption(
        "Outline → ensayo canónico → posts por canal. Revisa y edita en Obsidian antes de publicar."
    )

    choices = list_campaign_choices()
    if not choices:
        st.info("No hay campañas en `Campaigns/`.")
        return

    slug_labels = {slug: label for slug, label in choices}
    selected = st.selectbox("Campaña", list(slug_labels.values()))
    slug = next(s for s, label in slug_labels.items() if label == selected)

    cfg = build_editorial_llm_config()
    st.caption(f"Modelo editorial: `{cfg.label}` · requiere `OPENAI_API_KEY` o `GROQ_API_KEY`")

    force = st.checkbox("Sobrescribir archivos existentes", value=False)
    only_channels = st.multiselect(
        "Canales (para 'Generar canales')",
        list(ALL_CHANNELS),
        default=["newsletter", "youtube"],
    )

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        run_outline = st.button("1. Outline")
    with col2:
        run_essay = st.button("2. Ensayo")
    with col3:
        run_channels = st.button("3. Canales")
    with col4:
        run_all = st.button("Todo el pipeline", type="primary")

    def _report(results) -> None:
        for r in results:
            if r.skipped:
                st.warning(f"Omitido (ya existe): `{r.path.name}`")
            else:
                st.success(f"Generado: `{r.path}`")

    try:
        if run_outline:
            with st.spinner("Generando outline…"):
                _report([generate_outline(slug, config=cfg, force=force)])
        if run_essay:
            with st.spinner("Generando ensayo…"):
                _report([generate_essay(slug, config=cfg, force=force)])
        if run_channels:
            with st.spinner("Generando canales…"):
                ch = tuple(only_channels) if only_channels else None
                _report(generate_channels(slug, channels=ch, config=cfg, force=force))
        if run_all:
            with st.spinner("Pipeline completo…"):
                ch = tuple(only_channels) if only_channels else None
                _report(generate_all(slug, channels=ch, config=cfg, force=force))
    except Exception as exc:
        st.error(str(exc))
        return

    st.divider()
    st.subheader("Vista previa")
    from src.campaigns.editorial import get_campaign

    camp = get_campaign(slug)
    preview_options: list[tuple[str, Path]] = []
    if camp.outline_path.is_file():
        preview_options.append(("outline", camp.outline_path))
    if camp.essay_path.is_file():
        preview_options.append(("essay", camp.essay_path))
    for p in list_newsletter_files(camp):
        preview_options.append((f"newsletter: {p.stem}", p))
    for p in list_post_files(camp):
        preview_options.append((f"post: {p.stem}", p))

    if not preview_options:
        st.info("No hay archivos generados en esta campaña.")
        return

    labels = [label for label, _ in preview_options]
    choice = st.selectbox("Archivo", labels)
    path = preview_options[labels.index(choice)][1]
    if path.is_file():
        raw = path.read_text(encoding="utf-8")
        st.markdown(_strip_frontmatter(raw))
    else:
        st.info(f"Aún no existe `{path.name}`.")


def page_subscribers() -> None:
    st.header("Suscriptores")
    path = default_subscribers_path()
    st.caption(f"Archivo: `{path}`")

    if not path.is_file():
        st.warning("Crea `newsletters/suscriptores.md` en Obsidian con la tabla de suscriptores.")
        return

    subs = load_all_subscribers(path)
    active = [s for s in subs if s.active]
    st.write(f"**{len(active)}** activos · **{len(subs) - len(active)}** inactivos · **{len(subs)}** total")

    if subs:
        rows = [
            {
                "email": s.email,
                "nombre": s.name,
                "segmento": s.segment,
                "activo": "sí" if s.active else "no",
                "notas": s.notes,
            }
            for s in subs
        ]
        st.dataframe(rows, use_container_width=True)

    counts = list_segment_counts()
    if counts:
        st.subheader("Por segmento")
        for seg, n in counts.items():
            st.write(f"- `{seg}`: {n} destinatarios activos")

    st.info(
        "Edita la tabla en Obsidian (`suscriptores.md`). "
        "Cada destinatario recibe su **propio correo** (no van en CCO)."
    )


def page_log() -> None:
    st.header("Historial de envíos (local)")
    st.caption("Las estadísticas de aperturas y clics están en SMTP2GO Reports.")
    entries = read_send_log(30)
    if not entries:
        st.info("Aún no hay envíos registrados.")
        return
    for entry in entries:
        status = "✅" if entry.get("ok") else "❌"
        with st.expander(
            f"{status} {entry.get('at', '')[:19]} — {entry.get('subject', '')} [{entry.get('tag', '')}]"
        ):
            st.json(entry)
            tag = entry.get("tag")
            if tag:
                st.link_button("Ver estadísticas", activity_url(tag))


def page_config() -> None:
    st.header("Configuración")
    config = load_config()

    with st.form("config_form"):
        provider = st.selectbox(
            "Proveedor",
            ["smtp2go"],
            index=0,
        )
        token = st.text_input(
            "SMTP2GO API Key",
            value=config.api_key,
            type="password",
        )
        from_email = st.text_input("Remitente (email)", value=config.from_email)
        from_name = st.text_input("Remitente (nombre)", value=config.from_name)
        reply_to = st.text_input("Reply-To", value=config.reply_to)
        test_email = st.text_input("Email de prueba por defecto", value=config.test_email)
        md_dir = st.text_input("Carpeta Markdown", value=str(config.md_dir))
        submitted = st.form_submit_button("Guardar configuración")

    if submitted:
        save_settings(
            {
                "provider": provider,
                "api_key": token,
                "from_email": from_email,
                "from_name": from_name,
                "reply_to": reply_to,
                "test_email": test_email,
                "md_dir": md_dir,
            }
        )
        st.success("Guardado en data/newsletter_settings.json")
        st.rerun()

    st.divider()
    if st.button("Probar conexión"):
        result = test_connection(load_config())
        if result.get("ok"):
            st.success(
                f"Conectado — proveedor: `{result.get('provider', config.provider)}` · "
                f"from: {config.from_address}"
            )
        else:
            st.error(result.get("error", "Error de conexión"))

    st.markdown(
        """
**Campañas:** `Cerebro-Vincent/Campaigns/` — ver `docs/workflows/editorial-campaigns.md`.

**Suscriptores:** `Cerebro-Vincent/newsletters/suscriptores.md`.

**Estadísticas:** panel SMTP2GO (Reports).
        """
    )


def main() -> None:
    _init_state()
    config = load_config()
    if config.test_email and not st.session_state.test_email:
        st.session_state.test_email = config.test_email

    st.sidebar.title("📧 Newsletter")
    st.sidebar.caption(f"Academia Blockchain · {load_config().provider}")
    page = st.sidebar.radio(
        "Menú",
        ["Generar", "Componer", "Vista previa", "Enviar", "Campañas", "Suscriptores", "Historial", "Configuración"],
    )

    if page == "Generar":
        page_generate()
    elif page == "Componer":
        page_compose()
    elif page == "Vista previa":
        page_preview()
    elif page == "Enviar":
        page_send()
    elif page == "Campañas":
        page_editorial()
    elif page == "Suscriptores":
        page_subscribers()
    elif page == "Historial":
        page_log()
    else:
        page_config()


if __name__ == "__main__":
    main()
