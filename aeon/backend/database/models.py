from datetime import datetime
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Repository(Base):
    __tablename__ = "repositories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    url = Column(String(512), nullable=False)
    github_id = Column(String(64), unique=True, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    pipelines = relationship("Pipeline", back_populates="repository")


class Pipeline(Base):
    __tablename__ = "pipelines"

    id = Column(Integer, primary_key=True, index=True)
    repo_id = Column(Integer, ForeignKey("repositories.id"), nullable=False)
    name = Column(String(255), nullable=False)
    status = Column(String(64), default="pending", nullable=False)
    branch = Column(String(255), default="main", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    repository = relationship("Repository", back_populates="pipelines")
    logs = relationship("PipelineLog", back_populates="pipeline")
    incidents = relationship("Incident", back_populates="pipeline")


class PipelineLog(Base):
    __tablename__ = "pipeline_logs"

    id = Column(Integer, primary_key=True, index=True)
    pipeline_id = Column(Integer, ForeignKey("pipelines.id"), nullable=False)
    content = Column(Text, nullable=False)
    log_level = Column(String(32), default="INFO", nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)

    pipeline = relationship("Pipeline", back_populates="logs")


class Incident(Base):
    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True, index=True)
    pipeline_id = Column(Integer, ForeignKey("pipelines.id"), nullable=True)
    title = Column(String(512), nullable=False)
    description = Column(Text, nullable=True)
    severity = Column(String(32), default="medium", nullable=False)
    status = Column(String(32), default="open", nullable=False)
    root_cause = Column(Text, nullable=True)
    suggested_fix = Column(Text, nullable=True)
    confidence = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    resolved_at = Column(DateTime, nullable=True)

    pipeline = relationship("Pipeline", back_populates="incidents")
    actions = relationship("AgentAction", back_populates="incident")


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"

    id = Column(Integer, primary_key=True, index=True)
    workflow_name = Column(String(255), nullable=False)
    status = Column(String(64), default="pending", nullable=False)
    trigger = Column(String(128), default="manual", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class AgentAction(Base):
    __tablename__ = "agent_actions"

    id = Column(Integer, primary_key=True, index=True)
    incident_id = Column(Integer, ForeignKey("incidents.id"), nullable=True)
    action_type = Column(String(128), nullable=False)
    payload = Column(Text, nullable=True)
    result = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    incident = relationship("Incident", back_populates="actions")
