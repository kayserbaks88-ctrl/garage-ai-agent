from trimtech.core.registry import load_business

BUSINESSES = [
    "garage",
]

print("=" * 60)
print("TESTING ALL BUSINESSES")
print("=" * 60)

for business in BUSINESSES:
    print(f"\nLoading: {business}")

    try:
        config = load_business(business)

        print(f"✅ Name: {config.business_name}")
        print(f"   Type: {config.business_type}")
        print(f"   Services: {len(config.services)}")
        print(f"   Features Enabled: {sum(vars(config.features).values())}")

    except Exception as e:
        print(f"❌ FAILED: {e}")