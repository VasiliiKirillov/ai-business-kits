"""Тексты карточек для группы менеджеров."""
from .booking import phone_of
from .config import Config


def booking_card(cfg: Config, lid, client_name, f: dict, contact, item_line: str, price: str, model: str, sec: float, fmt=None) -> str:
    d, idc = f.get("doc") or {}, cfg.request.identity_document
    head = " · ".join(x for x in (d.get("full_name") or client_name,
                                  f"{idc.name} {d['number']}" if d.get("number") else "", d.get("nationality")) if x)
    phone = phone_of(cfg, f)
    rows = [f"📥 {cfg.request.noun.capitalize()} #{lid}", f"👤 {head}",
            f"📞 {' · '.join(x for x in (phone, contact) if x) or '-'}", f"🎯 {item_line}"]
    for fld in cfg.request.fields:
        v = f.get(fld.key)
        if fld.type in ("item", "phone") or v in (None, ""):
            continue
        if fld.key == cfg.pricing.quantity_field and str(v) == "1":
            continue
        rows.append(f"• {fld.label}: {fmt(fld, v) if fmt else v}")
    rows += [f"💰 {price}", "", f"🧠 {model} · {sec:.1f} c"]
    return "\n".join(rows)


def complaint_card(lid, client_name, contact, tail, model, sec) -> str:
    return "\n".join([f"😡 Жалоба #{lid} от {client_name}", f"Контакт: {contact or '-'}", "", tail, "", f"🧠 {model} · {sec:.1f} c"])
