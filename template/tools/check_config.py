"""python tools/check_config.py [config.yaml]: проверка конфига, что бот будет спрашивать, примеры цен и сгенерированные промпты."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from intake import prompts
from intake.catalog import Catalog
from intake.config import ConfigError, load, today
from intake import pricing


def main():
    try:
        cfg = load(sys.argv[1] if len(sys.argv) > 1 else None)
    except ConfigError as e:
        print(e)
        raise SystemExit(1)
    cat, r = Catalog(cfg), cfg.request
    print(f"OK: {cfg.business.name}. Источник: {cfg.data.source}, документы: {cfg.documents.engine}, "
          f"занятость: {cfg.availability.mode}, цены: {cfg.pricing.mode}\n")
    print(f"Бот спрашивает по очереди ({r.noun}):")
    for i, f in enumerate(r.fields, 1):
        flags = ", ".join(x for x in (f.type, "по умолчанию " + str(f.default) if f.default is not None else "",
                                      "только если неясно" if f.ask_only_if_unclear else "",
                                      "можно отказаться" if f.declinable else "") if x)
        print(f"  {i}. {f.key} ({flags}): {f.ask}")
    if r.identity_document.enabled:
        print(f"  + документ ({r.identity_document.name}): {', '.join(r.identity_document.fields)}")
    print("\nПримеры цен:")
    for it in cat.items[:5]:
        f = {k: v for k, v in {cfg.pricing.duration_field: 3, cfg.pricing.quantity_field: 1}.items() if k}
        c = pricing.calc(cfg, it, f)
        print(f"  {it.name}: {pricing.price_phrase(cfg, it, f)}" + (f"  [{c['formula']}]" if c else ""))
    if not cat.items:
        print("  (каталог пуст)")
    bad = [s for s in (cfg.model_dump_json(),) if "\u0451" in s or "\u2014" in s or "\u2013" in s]
    if bad:
        print("\nВНИМАНИЕ: в конфиге есть буква 'е с точками' или длинное тире, замени на обычную е и короткий дефис")
    print("\n===== ПРОМПТ РАЗБОРА =====\n" + prompts.parser_system(cfg, cat, today(cfg)))
    print("\n===== ПРОМПТ ЧАТА =====\n" + prompts.chat_system(cfg, cat, today(cfg), "<статус от кода>"))


if __name__ == "__main__":
    main()
