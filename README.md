python -m app.scripts.seed_v1

alembic revision --autogenerate -m "workspace availability final v2"
alembic upgrade head

uvicorn app.main:app --reload
