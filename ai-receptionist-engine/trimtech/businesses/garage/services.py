from __future__ import annotations

from trimtech.core.business import ServiceDefinition


GARAGE_SERVICES: tuple[ServiceDefinition, ...] = (
    ServiceDefinition(
        key="mot",
        name="MOT",
        duration_minutes=60,
        price=54.85,
        aliases=(
            "mot test",
            "m.o.t",
            "m.o.t.",
            "vehicle mot",
        ),
        metadata={
            "category": "inspection",
            "requires_vehicle": True,
            "supports_dvla": True,
        },
    ),
    ServiceDefinition(
        key="full_service",
        name="Full Service",
        duration_minutes=120,
        price=180.00,
        aliases=(
            "service",
            "full car service",
            "car service",
            "vehicle service",
        ),
        metadata={
            "category": "servicing",
            "requires_vehicle": True,
            "supports_dvla": True,
        },
    ),
    ServiceDefinition(
        key="diagnostic",
        name="Diagnostic",
        duration_minutes=45,
        price=65.00,
        aliases=(
            "diagnostics",
            "vehicle diagnostic",
            "car diagnostic",
            "fault diagnostic",
            "diagnostic check",
        ),
        metadata={
            "category": "diagnostics",
            "requires_vehicle": True,
            "supports_dvla": True,
            "requires_notes": True,
        },
    ),
    ServiceDefinition(
        key="oil_change",
        name="Oil Change",
        duration_minutes=30,
        price=75.00,
        aliases=(
            "oil",
            "oil and filter",
            "oil & filter",
            "oil change service",
        ),
        metadata={
            "category": "servicing",
            "requires_vehicle": True,
            "supports_dvla": True,
        },
    ),
)


def get_garage_services() -> tuple[ServiceDefinition, ...]:
    """
    Return all enabled garage services.
    """

    return tuple(
        service
        for service in GARAGE_SERVICES
        if service.enabled
    )


def get_garage_service(
    service_key: str,
) -> ServiceDefinition | None:
    """
    Find a garage service using its key, name or alias.
    """

    for service in GARAGE_SERVICES:
        if service.matches(service_key):
            return service

    return None