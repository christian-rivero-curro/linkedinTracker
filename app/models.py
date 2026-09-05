"""
Modelos ORM ligeros usados solo en el portal para lecturas.
"""
from sqlalchemy import Column, Integer, String, Text, Float, Boolean, ARRAY, TIMESTAMP
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Profile(Base):
    __tablename__ = "profile"
    id = Column(Integer, primary_key=True)
    raw_cv_text = Column(Text, nullable=False)
    location_preference = Column(String)
    remote_preference = Column(String)
    role_family = Column(ARRAY(String))
    min_salary = Column(Integer)


class JobOffer(Base):
    __tablename__ = "job_offer"
    id = Column(Integer, primary_key=True)
    external_id = Column(String, unique=True, nullable=False)
    title = Column(String, nullable=False)
    company = Column(String)
    location = Column(String)
    remote_type = Column(String)
    description = Column(Text, nullable=False)
    apply_link = Column(String, nullable=False)
    source = Column(String, nullable=False)
    salary_min = Column(Integer)
    salary_max = Column(Integer)
    posted_at = Column(TIMESTAMP)
    fetched_at = Column(TIMESTAMP)


class JobScore(Base):
    __tablename__ = "job_score"
    id = Column(Integer, primary_key=True)
    job_offer_id = Column(Integer)
    profile_id = Column(Integer)
    vector_similarity = Column(Float, nullable=False)
    llm_score = Column(Integer)
    llm_evaluated = Column(Boolean, default=False)
    pros = Column(ARRAY(String))
    cons = Column(ARRAY(String))
    missing_requirements = Column(ARRAY(String))
    final_score = Column(Float, nullable=False)
    status = Column(String, default="new")
