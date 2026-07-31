from __future__ import annotations

from trimtech.core.registry import load_business


def main() -> None:
    business = load_business("garage")

    print()
    print("BUSINESS LOADED SUCCESSFULLY")
    print("----------------------------")
    print("ID:", business.business_id)
    print("Type:", business.business_type)
    print("Name:", business.business_name)
    print("Timezone:", business.timezone_name)
    print("Currency:", business.currency_symbol)
    print()

    print("ENABLED FEATURES")
    print("----------------")
    for feature_name, enabled in business.features.to_dict().items():
        if enabled:
            print("✓", feature_name)

    print()
    print("GARAGE SERVICES")
    print("---------------")

    for service in business.enabled_services():
        print(
            f"✓ {service.name} | "
            f"{service.duration_minutes} minutes | "
            f"£{service.price:.2f}"
        )

    print()
    print("SERVICE TESTS")
    print("-------------")

    test_values = [
        "MOT test",
        "full car service",
        "diagnostics",
        "oil & filter",
    ]

    for value in test_values:
        resolved = business.resolve_service(value)

        if resolved:
            print(
                f"✓ {value!r} → "
                f"{resolved.key} / {resolved.name}"
            )
        else:
            print(f"✗ Could not resolve {value!r}")


if __name__ == "__main__":
    main()