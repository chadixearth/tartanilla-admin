from reportlab.lib.pagesizes import letter, A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, PageBreak
from reportlab.lib.units import inch, mm
from reportlab.platypus.tableofcontents import TableOfContents
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from django.http import HttpResponse
from datetime import datetime
from api.data import get_customers, get_owners, get_drivers
from tartanilla_admin.supabase import supabase
from django.conf import settings
import os
import json

class NumberedCanvas:
    def __init__(self, canvas, doc):
        self.canvas = canvas
        self.doc = doc

    def draw_page_number(self):
        self.canvas.setFont("Helvetica", 9)
        self.canvas.setFillColor(colors.grey)
        self.canvas.drawRightString(A4[0] - 30*mm, 20*mm, f"Page {self.canvas.getPageNumber()}")
        self.canvas.drawString(30*mm, 20*mm, "Tartanilla Tourism Management System")

def export_users_pdf(request):
    """Export users by type to PDF with professional design"""
    # Determine user type
    user_type = 'all'
    referer = request.META.get('HTTP_REFERER', '')
    
    if 'customers' in referer.lower():
        user_type = 'customers'
    elif 'drivers' in referer.lower():
        user_type = 'drivers'
    elif 'owners' in referer.lower():
        user_type = 'owners'
    
    filename = f"tartanilla_{user_type}_report_{datetime.now().strftime('%Y%m%d')}.pdf"
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    # Professional margins and layout
    doc = SimpleDocTemplate(
        response, 
        pagesize=A4,
        leftMargin=30*mm,
        rightMargin=30*mm,
        topMargin=1*mm,
        bottomMargin=15*mm
    )
    
    elements = []
    styles = getSampleStyleSheet()
    
    # Custom styles
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Title'],
        fontSize=24,
        textColor=colors.HexColor('#531B24'),
        spaceAfter=5*mm,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold'
    )
    
    subtitle_style = ParagraphStyle(
        'Subtitle',
        parent=styles['Normal'],
        fontSize=14,
        textColor=colors.HexColor('#666666'),
        spaceAfter=10*mm,
        alignment=TA_CENTER,
        fontName='Helvetica'
    )
    
    section_style = ParagraphStyle(
        'SectionHeader',
        parent=styles['Heading2'],
        fontSize=16,
        textColor=colors.HexColor('#531B24'),
        spaceBefore=8*mm,
        spaceAfter=4*mm,
        fontName='Helvetica-Bold',
        borderWidth=0,
        borderColor=colors.HexColor('#531B24'),
        borderPadding=2*mm
    )
    
    # Header with logo and company info
    header_table_data = []
    
    # Company name centered (no logo)
    company_name = Paragraph("""
        <font size="20" color="#531B24"><b>Tartanilla Tourism Management System</b><br/></font>
        <font size="10" color="#666666">Cebu City, 6000, Philippines.<br/></font>
        <font size="9" color="#666666">Administrative Report</font>

    """, 
    ParagraphStyle('CompanyName', parent=styles['Normal'], fontSize=12, textColor=colors.HexColor('#531B24'), alignment=TA_CENTER))
    
    elements.append(company_name)
    elements.append(Spacer(1, 15*mm))
    
    # Date generated (above the line, right-aligned)
    date_generated = Paragraph(
        f"Generated: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}", 
        ParagraphStyle('DateGen', parent=styles['Normal'], fontSize=9, textColor=colors.HexColor('#666666'), alignment=TA_RIGHT)
    )
    elements.append(date_generated)
    
    # Divider line (immediately after date)
    usable_width = A4[0] - 60*mm
    line_table = Table([['']], colWidths=[usable_width])
    line_table.setStyle(TableStyle([
        ('LINEBELOW', (0, 0), (-1, -1), 2, colors.HexColor('#531B24')),
    ]))
    elements.append(line_table)
    elements.append(Spacer(1, 6*mm))
    
    # Title
    title_map = {
        'customers': 'List of Registered Passengers',
        'drivers': 'List of Registered Drivers', 
        'owners': 'List of Registered Owners',
        'all': 'Complete User Registry Report'
    }
    
    subtitle_map = {
        'customers': 'Comprehensive passenger data and statistics',
        'drivers': 'Comprehensive driver data and statistics',
        'owners': 'Comprehensive owner data and statistics',
        'all': 'Comprehensive user data and statistics'
    }
    
    # Title and subtitle combined in single Paragraph
    title_content = Paragraph(f"""
        <font size="18" color="#531B24"><b>{title_map.get(user_type, 'User Report')}</b><br/></font>
        <font size="9" color="#666666">{subtitle_map.get(user_type, 'Comprehensive user data and statistics')}</font>
    """, 
    ParagraphStyle('TitleContent', parent=styles['Normal'], fontSize=24, textColor=colors.HexColor('#531B24'), alignment=TA_CENTER))
    
    elements.append(title_content)
    elements.append(Spacer(1, 10*mm))
    
    try:
        # Get users based on type
        if user_type == 'customers':
            users_data = get_customers()
            sections = [("Registered Passenger", users_data, colors.HexColor('#2E86AB'))]
        elif user_type == 'drivers':
            users_data = get_drivers()
            sections = [("Licensed Drivers", users_data, colors.HexColor('#A23B72'))]
        elif user_type == 'owners':
            users_data = get_owners()
            sections = [("Tartanilla Owners", users_data, colors.HexColor('#F18F01'))]
        else:
            users_response = supabase.table('users').select('*').execute()
            all_users = users_response.data if hasattr(users_response, 'data') else []
            
            tourists = [u for u in all_users if u.get('role') == 'tourist']
            drivers = [u for u in all_users if u.get('role') == 'driver']
            owners = [u for u in all_users if u.get('role') == 'owner']
            
            sections = [
                ("Registered Customers", tourists, colors.HexColor('#2E86AB')),
                ("Licensed Drivers", drivers, colors.HexColor('#A23B72')),
                ("Tartanilla Owners", owners, colors.HexColor('#F18F01'))
            ]
        
        # Summary cards
        summary_data = []
        total_users = 0
        for section_name, users, color in sections:
            total_users += len(users)
            summary_data.append([section_name, str(len(users))])
        
        if user_type != 'all':
            summary_data = [[sections[0][0], str(total_users)]]
        
        # Summary section
        elements.append(Paragraph("Executive Summary", section_style))
        
        summary_table = Table(summary_data, colWidths=[100*mm, 30*mm])
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#F8F9FA')),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#2C3E50')),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 11),
            ('ROWBACKGROUNDS', (0, 0), (-1, -1), [colors.white, colors.HexColor('#F8F9FA')]),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E9ECEF')),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
        
        elements.append(summary_table)
        elements.append(Spacer(1, 8*mm))
        
        # Detailed sections
        for section_name, users, color in sections:
            if users:
                elements.append(Paragraph(f"{section_name} Details", section_style))
                
                # Table headers
                table_data = [['Full Name', 'Email Address', 'Phone Number', 'Status']]
                
                for user in users:
                    first_name = user.get('first_name', '') or user.get('firstname', '')
                    last_name = user.get('last_name', '') or user.get('lastname', '')
                    name = f"{first_name} {last_name}".strip() or user.get('name', 'N/A')
                    
                    status = str(user.get('status', 'N/A')).title()
                    status_color = colors.HexColor('#28A745') if status == 'Active' else colors.HexColor('#DC3545') if status == 'Suspended' else colors.HexColor('#FFC107')
                    
                    table_data.append([
                        name,
                        user.get('email', 'N/A'),
                        user.get('phone', 'N/A'),
                        status
                    ])
                
                # Professional table
                table = Table(table_data, colWidths=[45*mm, 55*mm, 35*mm, 25*mm])
                
                table_style = [
                    ('BACKGROUND', (0, 0), (-1, 0), color),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                    ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                    ('FONTSIZE', (0, 0), (-1, 0), 10),
                    ('FONTSIZE', (0, 1), (-1, -1), 9),
                    ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8F9FA')]),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#DEE2E6')),
                    ('TOPPADDING', (0, 0), (-1, -1), 6),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                    ('LEFTPADDING', (0, 0), (-1, -1), 8),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 8),
                ]
                
                table.setStyle(TableStyle(table_style))
                elements.append(table)
                elements.append(Spacer(1, 6*mm))
        
        # Footer info
        elements.append(Spacer(1, 10*mm))
        footer_style = ParagraphStyle('Footer', parent=styles['Normal'], fontSize=8, textColor=colors.HexColor('#6C757D'), alignment=TA_CENTER)
        elements.append(Paragraph("This report is confidential and intended for administrative use only.", footer_style))
        elements.append(Paragraph("© 2024 Tartanilla Tourism Management System. All rights reserved.", footer_style))
        
    except Exception as e:
        error_style = ParagraphStyle('Error', parent=styles['Normal'], fontSize=12, textColor=colors.red)
        elements.append(Paragraph(f"Error generating report: {str(e)}", error_style))
    
    # Build with page numbers
    def add_page_number(canvas, doc):
        canvas.saveState()
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(colors.HexColor('#6C757D'))
        canvas.drawRightString(A4[0] - 30*mm, 15*mm, f"Page {canvas.getPageNumber()}")
        canvas.drawString(30*mm, 15*mm, "Tartanilla Tourism Management System")
        canvas.restoreState()
    
    doc.title = filename  # Set document title(we can see it in PDF properties or in web tab)

    doc.build(elements, onFirstPage=add_page_number, onLaterPages=add_page_number)
    
    # Log to audit trail
    try:
        admin_email = request.COOKIES.get('admin_email', 'Unknown Admin')
        admin_id = request.COOKIES.get('admin_user_id', 'Unknown')
        
        audit_data = {
            'user_id': admin_id,
            'username': admin_email,
            'role': 'admin',
            'action': 'PDF_EXPORT',
            'entity_name': 'USER_REPORT',
            'entity_id': user_type,
            'new_data': {
                'report_type': user_type,
                'filename': filename,
                'user_count': total_users,
                'timestamp': datetime.now().isoformat()
            },
            'ip_address': request.META.get('REMOTE_ADDR', 'Unknown')
        }
        
        supabase.table('audit_logs').insert(audit_data).execute()
    except Exception as e:
        print(f"Failed to log PDF export: {e}")
    
    return response