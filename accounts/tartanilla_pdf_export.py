from reportlab.lib.pagesizes import letter, A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.units import inch, mm
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from django.http import HttpResponse
from datetime import datetime
from tartanilla_admin.supabase import supabase
from django.conf import settings
import os
import json

def export_tartanillas_pdf(request):
    """Export tartanilla carriages grouped by owner to PDF"""
    filename = f"tartanilla_carriages_report_{datetime.now().strftime('%Y%m%d')}.pdf"
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
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
        fontName='Helvetica-Bold'
    )
    
    # Header with company info (no logo, centered)
    elements.append(Spacer(1, 10*mm))
    company_name = Paragraph("""
        <font size="20" color="#531B24"><b>Tartanilla Tourism Management System</b><br/></font>
        <font size="10" color="#666666">Cebu City, 6000, Philippines.<br/></font>
        <font size="9" color="#666666">Carriages & Owners Report</font>
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
    title_content = Paragraph(f"""
        <font size="18" color="#531B24"><b>Tartanilla Carriages Registry</b><br/></font>
        <font size="9" color="#666666">Complete listing of all registered carriages by owner</font>
    """, 
    ParagraphStyle('TitleContent', parent=styles['Normal'], fontSize=24, textColor=colors.HexColor('#531B24'), alignment=TA_CENTER))
    
    elements.append(title_content)
    elements.append(Spacer(1, 10*mm))
    
    try:
        # Get all carriages with owner information
        carriages_response = supabase.table('tartanilla_carriages').select('*').execute()
        carriages = carriages_response.data if hasattr(carriages_response, 'data') else []
        
        # Get all users for owner lookup
        users_response = supabase.table('users').select('*').execute()
        users = {user['id']: user for user in users_response.data} if hasattr(users_response, 'data') else {}
        
        # Group carriages by owner
        owners_carriages = {}
        unassigned_carriages = []
        
        for carriage in carriages:
            owner_id = carriage.get('assigned_owner_id')
            if owner_id and str(owner_id).strip() and owner_id in users:
                if owner_id not in owners_carriages:
                    owners_carriages[owner_id] = {
                        'owner': users[owner_id],
                        'carriages': []
                    }
                owners_carriages[owner_id]['carriages'].append(carriage)
            else:
                unassigned_carriages.append(carriage)
        
        total_carriages = len(carriages)
        total_owners = len([owner_id for owner_id in owners_carriages.keys() if owners_carriages[owner_id]['carriages']])
        
        # Summary section
        elements.append(Paragraph("Executive Summary", section_style))
        
        summary_data = [
            ['Total Registered Carriages', str(total_carriages)],
            ['Active Owners', str(total_owners)],
            ['Unassigned Carriages', str(len(unassigned_carriages))]
        ]
        
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
        
        # Owners and their carriages
        for owner_id, data in owners_carriages.items():
            owner = data['owner']
            owner_carriages = data['carriages']
            
            # Skip if no carriages
            if not owner_carriages:
                continue
                
            # Owner header - name or email
            owner_display = owner.get('name')
            if not owner_display:
                first_name = owner.get('first_name', '').strip()
                last_name = owner.get('last_name', '').strip()
                if first_name or last_name:
                    owner_display = f"{first_name} {last_name}".strip()
                else:
                    owner_display = owner.get('email', 'Unknown Owner')
            
            elements.append(Paragraph(f"{owner_display}", section_style))
            
            # Owner contact info
            owner_info = f"Email: {owner.get('email', 'N/A')}"
            if owner.get('phone'):
                owner_info += f" | Phone: {owner.get('phone')}"
            elements.append(Paragraph(owner_info, ParagraphStyle('OwnerInfo', parent=styles['Normal'], fontSize=10, textColor=colors.HexColor('#666666'), spaceAfter=4*mm)))
            
            # Carriages table - simplified format
            table_data = [['Plate Number', 'Status', 'Capacity', 'Eligibility']]
            
            for carriage in owner_carriages:
                table_data.append([
                    carriage.get('plate_number', 'N/A'),
                    str(carriage.get('status', 'N/A')).replace('_', ' ').title(),
                    f"{carriage.get('capacity', 'N/A')} persons",
                    str(carriage.get('eligibility', 'N/A')).title()
                ])
            
            # Create table
            table = Table(table_data, colWidths=[40*mm, 35*mm, 35*mm, 40*mm])
            
            table_style = [
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#531B24')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, 0), 9),
                ('FONTSIZE', (0, 1), (-1, -1), 8),
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
        
        # Unassigned carriages section
        if unassigned_carriages:
            elements.append(Paragraph(f"Unassigned Carriages ({len(unassigned_carriages)})", section_style))
            
            table_data = [['Plate Number', 'Status', 'Capacity', 'Eligibility']]
            
            for carriage in unassigned_carriages:
                table_data.append([
                    carriage.get('plate_number', 'N/A'),
                    str(carriage.get('status', 'N/A')).replace('_', ' ').title(),
                    f"{carriage.get('capacity', 'N/A')} persons",
                    str(carriage.get('eligibility', 'N/A')).title()
                ])
            
            table = Table(table_data, colWidths=[40*mm, 35*mm, 35*mm, 40*mm])
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#DC3545')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, 0), 9),
                ('FONTSIZE', (0, 1), (-1, -1), 8),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8F9FA')]),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#DEE2E6')),
                ('TOPPADDING', (0, 0), (-1, -1), 6),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                ('LEFTPADDING', (0, 0), (-1, -1), 8),
                ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ]))
            
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
            'entity_name': 'TARTANILLA_CARRIAGES',
            'entity_id': 'all_carriages',
            'new_data': {
                'report_type': 'tartanilla_carriages',
                'filename': filename,
                'total_carriages': total_carriages,
                'total_owners': total_owners,
                'timestamp': datetime.now().isoformat()
            },
            'ip_address': request.META.get('REMOTE_ADDR', 'Unknown')
        }
        
        supabase.table('audit_logs').insert(audit_data).execute()
    except Exception as e:
        print(f"Failed to log tartanilla PDF export: {e}")
    
    return response