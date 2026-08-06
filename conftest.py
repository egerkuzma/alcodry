# Пустой conftest в корне: по нему pytest кладёт корень проекта в sys.path,
# и тесты видят пакет `app` без установки и без PYTHONPATH.
