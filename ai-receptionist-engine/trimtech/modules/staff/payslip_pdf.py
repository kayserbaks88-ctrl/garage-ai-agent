"""In-memory PDF rendering from an immutable payroll snapshot, no external URLs."""
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from html import escape
import reportlab
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

FONT = 'StaffVera'
if FONT not in pdfmetrics.getRegisteredFontNames():
    pdfmetrics.registerFont(TTFont(FONT,str(Path(reportlab.__file__).parent/'fonts/Vera.ttf')))


def render(slip):
    output=BytesIO()
    doc=SimpleDocTemplate(output,pagesize=A4,rightMargin=42,leftMargin=42,topMargin=38,bottomMargin=42,
                          title=f"Payslip {slip['id']}",author='TrimTech Staff Manager')
    green=colors.HexColor('#176644')
    normal=ParagraphStyle('body',fontName=FONT,fontSize=10,leading=15,textColor=colors.HexColor('#243d33'),spaceAfter=8)
    small=ParagraphStyle('small',parent=normal,fontSize=8,leading=12,textColor=colors.HexColor('#53645b'))
    title=ParagraphStyle('title',parent=normal,fontSize=24,leading=30,textColor=green,spaceAfter=12)
    heading=ParagraphStyle('heading',parent=normal,fontSize=13,leading=18,textColor=green,spaceBefore=12)
    def p(text,style=normal): return Paragraph(escape(str(text)),style)
    def amount(value): return f"£{Decimal(str(value)):,.2f}"
    result=slip['result']; profile=slip['profile']
    flow=[p('TRIMTECH  /  STAFF MANAGER',small),p('Draft payroll preview' if slip['status']=='draft' else 'Payslip',title),
          p(slip['employer_name']),p(slip['employee_name']),
          p(f"Payslip #{slip['id']}  |  Payment date: {slip['payment_date']}"),
          p(f"Work period: {slip['period_start']} to {slip['period_end']}"),
          p(f"{slip['frequency'].title()} pay  |  Tax year {slip['tax_year']}  |  Period {slip['tax_period']}",small),
          p(f"Tax code: {profile['tax_code']} ({profile['tax_basis']})  |  NI category: {profile['ni_category']}",small),Spacer(1,8)]
    rows=[[p('Earnings and deductions'),p('Amount')],
          [p(f"Gross pay - {Decimal(slip['payable_minutes'])/60:.2f} payable hours at {amount(slip['hourly_rate'])}/hour"),p(amount(slip['gross_pay']))]]
    for key,label in [('paye','PAYE (negative amount is a refund)'),('employee_ni','Employee National Insurance'),
                      ('employee_pension','Employee pension'),('deductions','Total deductions'),('net_pay','NET PAY')]:
        rows.append([p(label),p(amount(result[key]))])
    table=Table(rows,colWidths=[365,146],hAlign='LEFT')
    table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#edf4ef')),
        ('BACKGROUND',(0,-1),(-1,-1),colors.HexColor('#d9eddf')),('VALIGN',(0,0),(-1,-1),'TOP'),
        ('LINEBELOW',(0,0),(-1,-1),.4,colors.HexColor('#d9e3dc')),('LEFTPADDING',(0,0),(-1,-1),10),
        ('RIGHTPADDING',(0,0),(-1,-1),10),('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),5)]))
    flow.extend([table,p('Employer pension contribution',heading),
        p(amount(result['employer_pension'])),
        p('This is paid into your pension by your employer and does not reduce your net pay.',small),p('Tax year to date',heading),
        p(f"Taxable pay {amount(result['taxable_pay_ytd'])}  |  PAYE {amount(result['paye_ytd'])}"),
        p('Includes recorded opening balances from earlier payroll.',small),
        p(f"Pension: {profile['pension_method'].replace('_',' ')}; {profile['pension_basis']} earnings. Pension tax relief {amount(result['pension_tax_relief'])}.",small),
        Spacer(1,8),p('This document records payroll calculations and does not confirm a bank payment. TrimTech does not submit payroll to HMRC. The employer remains responsible for HMRC/RTI submissions.',small)])
    def footer(canvas,document):
        canvas.setFont(FONT,8); canvas.setFillColor(colors.HexColor('#53645b'))
        canvas.drawString(42,24,'Private and confidential')
        canvas.drawRightString(A4[0]-42,24,f"Payslip {slip['id']}  |  {document.page}")
    doc.build(flow,onFirstPage=footer,onLaterPages=footer)
    return output.getvalue()
