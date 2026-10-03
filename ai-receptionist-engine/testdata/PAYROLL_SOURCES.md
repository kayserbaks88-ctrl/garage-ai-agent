# HMRC payroll fixtures, 2026/27

The JSON files are normalized numeric rows from HMRC's public payroll developer
test data, downloaded 3 October 2026. Source: HM Revenue & Customs, Crown copyright,
reused under the Open Government Licence v3.0. They contain synthetic data only.

- [HMRC test-data publication](https://www.gov.uk/government/publications/software-developers-payroll-test-data-2026-to-2027)
- [PAYE v1.1 archive](https://assets.publishing.service.gov.uk/media/696f9b5f2b64f0e8c32e33a4/Tax-test-data-examples-2026-27-v1-1.zip)
- [NI v1.0 archive](https://assets.publishing.service.gov.uk/media/69676c2297d42030a67b0d60/NI-test-data-examples-from-April-2026-v1-0__1_.zip)
- [Open Government Licence](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/)

PAYE: 168 rows across the rest-of-UK, Scottish and Welsh workbooks. Monetary values
are normalized to pence to remove spreadsheet binary floating-point artefacts.
Opening tax and taxable pay are derived from each row's supplied totals and period
amounts. Tests allow HMRC's documented one-penny tolerance.

NI: 448 regular weekly/monthly rows from the employee NI and Freeport/Investment
Zone workbooks. All comparisons are exact. Director and other-frequency rows are
excluded because those calculations are outside the supported product scope.

Calculation references:

- [PAYE routines v24](https://www.gov.uk/government/publications/payroll-technical-specifications-income-tax)
- [NI software guidance](https://www.gov.uk/government/publications/payroll-technical-specifications-national-insurance)
- [2026/27 rates and thresholds](https://www.gov.uk/guidance/rates-and-thresholds-for-employers-2026-to-2027)
- [Pension earnings thresholds](https://www.thepensionsregulator.gov.uk/employers/new-employers/im-an-employer-who-has-to-provide-a-pension/declare-your-compliance/ongoing-duties-for-employers/earnings-thresholds)

Passing these fixtures is not a claim of HMRC recognition or certification.
