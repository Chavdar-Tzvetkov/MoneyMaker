# db/db_session.py
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from dotenv import load_dotenv
from db.models import Base

load_dotenv()

connection_string = os.getenv("MSSQL_CONN_STR")
engine = create_engine(connection_string, pool_pre_ping=True, pool_recycle=3600)
SessionLocal = scoped_session(sessionmaker(bind=engine))

def create_db():
    Base.metadata.create_all(bind=engine)