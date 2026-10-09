"""Owner-only billing and a separately signed, CSRF-exempt Staff webhook."""
import logging

import stripe
from flask import abort, flash, g, jsonify, redirect, render_template, request, url_for

from trimtech.modules.staff import accounts, billing
from trimtech.modules.staff.manager_auth import billing_owner_required, ERRORS
from trimtech.modules.staff.stripe_gateway import BillingUnavailable, Gateway, configuration, verified_event
from trimtech.modules.staff.trusted_proxy import client_address

logger = logging.getLogger(__name__)


def register_routes(staff):
    bp = staff.staff_blueprint

    @bp.get('/<business_slug>/subscription')
    @billing_owner_required
    def subscription(business_slug):
        plan, error = None, ''
        try:
            state = billing.summary(business_slug)
        except ERRORS:
            abort(503,description='Billing records are temporarily unavailable.')
        try:
            config = configuration()
            gateway = Gateway(config)
            gateway.merchant()
            plan = gateway.price()
        except BillingUnavailable as failure:
            error = str(failure)
        except stripe.StripeError:
            error = 'Stripe is temporarily unavailable. Your subscription has not been changed.'
        return render_template('staff_subscription.html',business_slug=business_slug,trial=g.staff_trial,
            billing=state,plan=plan,error=error,csrf_token=staff._get_csrf_token)

    def action(business_slug, kind):
        try:
            if not accounts.limited('staff-billing-'+kind,business_slug,client_address(),str(staff.current_app.secret_key)):
                abort(429,description='Too many billing requests. Please try again in 15 minutes.')
            if kind == 'checkout':
                if request.form.get('subscription_consent') != 'yes':
                    abort(400,description='Confirm the recurring subscription before continuing to Checkout.')
                target = billing.checkout(business_slug,g.staff_administrator['id'])
                if target:
                    return redirect(target,code=303)
                flash('Billing status checked. Review your current subscription below before starting another checkout.','success')
            elif kind == 'portal':
                return redirect(billing.portal(business_slug),code=303)
            else:
                billing.refresh(business_slug)
                flash('Subscription status refreshed securely from Stripe.','success')
        except BillingUnavailable as failure:
            flash(str(failure),'error')
        except (*ERRORS,stripe.StripeError):
            logger.warning('Staff billing action unavailable: action=%s',kind)
            flash('Billing is temporarily unavailable. No new access has been granted. Please retry this request; do not start a second subscription elsewhere.','error')
        return redirect(url_for('staff.subscription',business_slug=business_slug))

    @bp.post('/<business_slug>/subscription/checkout')
    @billing_owner_required
    def billing_checkout(business_slug):
        return action(business_slug,'checkout')

    @bp.post('/<business_slug>/subscription/portal')
    @billing_owner_required
    def billing_portal(business_slug):
        return action(business_slug,'portal')

    @bp.post('/<business_slug>/subscription/refresh')
    @billing_owner_required
    def billing_refresh(business_slug):
        return action(business_slug,'refresh')

    @bp.post('/billing/webhook')
    def billing_webhook():
        # Bound even chunked/unknown-length bodies, and do not parse form data first.
        if request.content_length and request.content_length > 262144:
            abort(413)
        raw = request.stream.read(262145)
        if len(raw) > 262144:
            abort(413)
        try:
            config = configuration()
        except BillingUnavailable:
            return jsonify(error='billing_unavailable'),503
        try:
            event = verified_event(raw,request.headers.get('Stripe-Signature'),config)
        except (ValueError,TypeError,KeyError,stripe.SignatureVerificationError):
            return jsonify(error='invalid_signature_or_payload'),400
        try:
            result = billing.process_event(event,config)
        except (ValueError,TypeError,KeyError):
            return jsonify(error='invalid_event'),400
        except (*ERRORS,BillingUnavailable,stripe.StripeError):
            # Nothing is acknowledged as processed on a DB/API failure: Stripe can retry.
            logger.warning('Staff billing webhook processing deferred')
            return jsonify(error='retry_later'),503
        return jsonify(result=result),200
