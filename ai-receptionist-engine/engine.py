import os

BUSINESS = os.getenv("BUSINESS", "barber")

if BUSINESS == "garage":
    from business_configs import garage as CONFIG
    from integrations import garage_agent

elif BUSINESS == "barber":
    from business_configs import barber as CONFIG

elif BUSINESS == "cake":
    from business_configs import cake as CONFIG

elif BUSINESS == "estate":
    from business_configs import estate as CONFIG


def get_questions():
    return CONFIG.QUESTIONS


def get_business_name():
    return CONFIG.BUSINESS_NAME


def get_services():
    return getattr(CONFIG, "SERVICES", {})