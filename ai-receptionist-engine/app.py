from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from engine import BUSINESS

app = Flask(__name__)

reply = "Debug reply"
reply = "Configuration error."
@app.route("/whatsapp", methods=["POST"])
def whatsapp():

    incoming = request.values.get("Body","")
    phone = request.values.get("From","")
    print("BUSINESS =", BUSINESS)
    
    if BUSINESS == "garage":
        from integrations.garage_agent import handle_message
        profile_name = request.values.get("ProfileName", "")
        reply = handle_message(incoming, phone, profile_name)

    elif BUSINESS == "barber":
        from integrations.barber_agent import handle_message

        profile_name = request.values.get("ProfileName", "")

        reply = handle_message(
            incoming,
            phone,
            profile_name
        )
 
    elif BUSINESS == "lead_gen":
        from integrations.lead_gen_agent import handle_message

        profile_name = request.values.get("ProfileName", "")

        reply = handle_message(
            incoming,
            phone,
            profile_name
        )
   
    elif BUSINESS == "quote_builder":
        from integrations.quote_builder_agent import handle_message

        profile_name = request.values.get("ProfileName", "")

        num_media = int(request.values.get("NumMedia", 0))
        media_urls = []

        for i in range(num_media):
            media_url = request.values.get(f"MediaUrl{i}")
            if media_url:
               media_urls.append(media_url)

            reply = handle_message(
                phone=phone,
                text=incoming,
                profile_name=profile_name,
                media_urls=media_urls,
            )
    print("REPLY =", reply)
    resp = MessagingResponse()
    resp.message(reply)

    return str(resp)

    