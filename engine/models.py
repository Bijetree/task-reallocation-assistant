from dataclasses import dataclass, field
from engine.config import ROLE_LEAD, APPROVER_ROLES

@dataclass
class Factor:
    name: str
    value: float
    weight: float
    note: str

    @property
    def contribution(self):
        return self.value * self.weight

@dataclass
class Candidate:
    member_id: int
    name: str
    factors: list = field(default_factory=list)
    score: float = 0.0

    def factor_values(self):
        return {f.name: f.value for f in self.factors}

    def breakdown(self):
        return {f.name: round(f.contribution, 4) for f in self.factors}

def is_lead(member):
    return bool(member.get("role")) == ROLE_LEAD

def can_approve(member):
    return bool(member.get("role")) in APPROVER_ROLES