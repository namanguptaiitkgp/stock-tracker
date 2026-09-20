"""Seed the `known_sharks` table with well-known Indian HNI / shark investors.

Run via:
    from app.services.smart_money.known_sharks_seed import seed_known_sharks
    await seed_known_sharks()

Idempotent — existing canonical rows are left untouched.
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from app.db.session import async_session
from app.models.smart_money import KnownShark

logger = logging.getLogger(__name__)


SHARKS: list[dict] = [
    {"canonical": "Ashish Kacholia", "display": "Ashish Kacholia", "aliases": ["ASHISH DHAWAN", "KACHOLIA ASHISH"]},
    {"canonical": "Vijay Kedia", "display": "Vijay Kedia", "aliases": ["KEDIA VIJAY", "VIJAY KISHANLAL KEDIA"]},
    {"canonical": "Dolly Khanna", "display": "Dolly Khanna", "aliases": ["KHANNA DOLLY"]},
    {"canonical": "Rakesh Jhunjhunwala", "display": "Rakesh Jhunjhunwala (Late) / Rekha Jhunjhunwala", "aliases": ["REKHA JHUNJHUNWALA", "JHUNJHUNWALA RAKESH", "RAKESH RADHESHYAM JHUNJHUNWALA"]},
    {"canonical": "Mukul Agrawal", "display": "Mukul Agrawal", "aliases": ["AGRAWAL MUKUL", "MUKUL MAHAVIR AGRAWAL"]},
    {"canonical": "Porinju Veliyath", "display": "Porinju Veliyath", "aliases": ["VELIYATH PORINJU"]},
    {"canonical": "Anil Kumar Goel", "display": "Anil Kumar Goel", "aliases": ["GOEL ANIL KUMAR"]},
    {"canonical": "Ashish Dhawan", "display": "Ashish Dhawan", "aliases": ["DHAWAN ASHISH"]},
    {"canonical": "Sunil Singhania", "display": "Sunil Singhania / Abakkus", "aliases": ["SINGHANIA SUNIL", "ABAKKUS ASSET MANAGER"]},
    {"canonical": "Radhakishan Damani", "display": "Radhakishan Damani", "aliases": ["DAMANI RADHAKISHAN", "DAMANI R K"]},
    {"canonical": "Nemish Shah", "display": "Nemish Shah (Enam)", "aliases": ["SHAH NEMISH", "ENAM SECURITIES"]},
    {"canonical": "Ramesh Damani", "display": "Ramesh Damani", "aliases": ["DAMANI RAMESH"]},
    {"canonical": "Vanaja Sundar Iyer", "display": "Vanaja Sundar Iyer", "aliases": ["IYER VANAJA SUNDAR"]},
    {"canonical": "Dilipkumar Lakhi", "display": "Dilipkumar Lakhi", "aliases": ["LAKHI DILIPKUMAR", "LAKHI DILIP KUMAR"]},
    {"canonical": "Hitesh Satishchandra Doshi", "display": "Hitesh Doshi (Suzlon)", "aliases": ["DOSHI HITESH", "HITESH DOSHI"]},
    {"canonical": "Mohnish Pabrai", "display": "Mohnish Pabrai (Pabrai Funds)", "aliases": ["PABRAI MOHNISH", "PABRAI WAGONS"]},
    {"canonical": "Parag Parikh Financial Advisory Services", "display": "PPFAS", "aliases": ["PPFAS", "PARAG PARIKH"]},
    {"canonical": "Azim Premji", "display": "Azim Premji / Hasham Investment", "aliases": ["PREMJI INVEST", "HASHAM INVESTMENT"]},
    {"canonical": "Rajiv Khanna", "display": "Rajiv Khanna", "aliases": ["KHANNA RAJIV"]},
    {"canonical": "Shankar Sharma", "display": "Shankar Sharma", "aliases": ["SHARMA SHANKAR"]},
    {"canonical": "Bharat Shah", "display": "Bharat Shah (ASK)", "aliases": ["SHAH BHARAT"]},
    {"canonical": "Saurabh Mukherjea", "display": "Saurabh Mukherjea / Marcellus", "aliases": ["MARCELLUS INVESTMENT MANAGER", "MUKHERJEA SAURABH"]},
    {"canonical": "Vallabh Bhanshali", "display": "Vallabh Bhanshali (Enam)", "aliases": ["BHANSHALI VALLABH"]},
    {"canonical": "Samir Arora", "display": "Samir Arora (Helios)", "aliases": ["HELIOS CAPITAL", "ARORA SAMIR"]},
    {"canonical": "Motilal Oswal", "display": "Motilal Oswal", "aliases": ["OSWAL MOTILAL", "MOTILAL OSWAL FINANCIAL SERVICES"]},
    {"canonical": "Basant Maheshwari", "display": "Basant Maheshwari", "aliases": ["MAHESHWARI BASANT"]},
    {"canonical": "Raamdeo Agrawal", "display": "Raamdeo Agrawal (MOSL)", "aliases": ["AGRAWAL RAAMDEO"]},
    {"canonical": "Akash Prakash", "display": "Akash Prakash (Amansa)", "aliases": ["AMANSA HOLDINGS", "PRAKASH AKASH"]},
    {"canonical": "Nikhil Vora", "display": "Nikhil Vora (Sixth Sense)", "aliases": ["SIXTH SENSE VENTURES", "VORA NIKHIL"]},
    {"canonical": "Kenneth Andrade", "display": "Kenneth Andrade (Old Bridge)", "aliases": ["OLD BRIDGE CAPITAL", "ANDRADE KENNETH"]},
]


async def seed_known_sharks() -> dict:
    inserted = 0
    skipped = 0
    async with async_session() as session:
        result = await session.execute(select(KnownShark.canonical_name))
        existing = {c for (c,) in result.all()}

        for s in SHARKS:
            if s["canonical"] in existing:
                skipped += 1
                continue
            session.add(
                KnownShark(
                    canonical_name=s["canonical"],
                    display_name=s["display"],
                    aliases=s.get("aliases") or [],
                    active=True,
                )
            )
            inserted += 1

        await session.commit()
    logger.info("seeded known_sharks: inserted=%d skipped=%d", inserted, skipped)
    return {"inserted": inserted, "skipped": skipped}
