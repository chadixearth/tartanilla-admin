from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from django.http import HttpResponse
from datetime import datetime, timedelta
from tartanilla_admin.supabase import supabase
from django.conf import settings
import os
import traceback

def export_earnings_pdf(request):
    """Export earnings and revenue report to PDF with dynamic date ranges"""
    # Get parameters from request
    period = request.GET.get('period', 'all')
    date_from = request.GET.get('date_from', '').strip()
    date_to = request.GET.get('date_to', '').strip()
    group_by = request.GET.get('group_by', 'monthly').strip()
    
    now = datetime.now()
    
    # Handle dynamic date ranges from Sales Report modal
    if date_from and date_to:
        try:
            start_date = datetime.fromisoformat(date_from).replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = datetime.fromisoformat(date_to).replace(hour=23, minute=59, second=59, microsecond=999999)
            period_label = f"Custom Range ({start_date.strftime('%b %d, %Y')} - {end_date.strftime('%b %d, %Y')})"
        except ValueError:
            date_from = date_to = None
    
    # Calculate date range based on period if no custom dates provided
    if not date_from or not date_to:
        if period == 'today':
            start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = now.replace(hour=23, minute=59, second=59, microsecond=999999)
            period_label = "Today"
        elif period == 'week':
            days_since_monday = now.weekday()
            start_date = (now - timedelta(days=days_since_monday)).replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = (start_date + timedelta(days=6)).replace(hour=23, minute=59, second=59, microsecond=999999)
            period_label = "This Week"
        elif period == 'month':
            start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            next_month = start_date.replace(month=start_date.month + 1) if start_date.month < 12 else start_date.replace(year=start_date.year + 1, month=1)
            end_date = (next_month - timedelta(days=1)).replace(hour=23, minute=59, second=59, microsecond=999999)
            period_label = "This Month"
        else:  # all time
            start_date = None
            end_date = None
            period_label = "All Time"
    
    # Generate filename based on report type
    if date_from and date_to:
        filename = f"tartanilla_sales_report_{group_by}_{now.strftime('%Y%m%d_%H%M')}.pdf"
    else:
        filename = f"tartanilla_earnings_report_{period}_{now.strftime('%Y%m%d')}.pdf"
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
    
    # Header with company info (no logo, centered)
    elements.append(Spacer(1, 10*mm))
    company_name = Paragraph("""
        <font size="20" color="#531B24"><b>Tartanilla Tourism Management System</b><br/></font>
        <font size="10" color="#666666">Cebu City, 6000, Philippines.<br/></font>
        <font size="9" color="#666666">Earnings & Revenue Report</font>
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
    
    # Title - Dynamic based on report type
    if date_from and date_to:
        title_content = Paragraph(f"""
            <font size="17" color="#531B24"><b>Earnings Report</b><br/></font>
            <font size="9" color="#666666">Earnings analysis grouped by {group_by} - {period_label}</font>
        """, 
        ParagraphStyle('TitleContent', parent=styles['Normal'], fontSize=24, textColor=colors.HexColor('#531B24'), alignment=TA_CENTER))
    else:
        title_content = Paragraph(f"""
            <font size="18" color="#531B24"><b>Earnings & Revenue Report</b><br/></font>
            <font size="9" color="#666666">Financial overview and driver earnings - {period_label}</font>
        """, 
        ParagraphStyle('TitleContent', parent=styles['Normal'], fontSize=24, textColor=colors.HexColor('#531B24'), alignment=TA_CENTER))
    
    elements.append(title_content)
    elements.append(Spacer(1, 10*mm))
    
    try:
        # Get earnings data with date filtering and timeout handling
        earnings_data = []
        try:
            earnings_query = supabase.table('earnings').select('*')
            if start_date and end_date:
                earnings_query = earnings_query.gte('earning_date', start_date.isoformat()).lte('earning_date', end_date.isoformat())
            earnings_response = earnings_query.execute()
            earnings_data = earnings_response.data if hasattr(earnings_response, 'data') else []
        except Exception as db_error:
            print(f"Database connection error for earnings: {db_error}")
            earnings_data = []
        
        # Filter out reversed earnings
        valid_earnings = [e for e in earnings_data if (e.get('status') or '').lower() != 'reversed']
        
        # Get payouts data with date filtering and timeout handling
        payouts_data = []
        try:
            payouts_query = supabase.table('payouts').select('*')
            if start_date and end_date:
                payouts_query = payouts_query.gte('payout_date', start_date.isoformat()).lte('payout_date', end_date.isoformat())
            payouts_response = payouts_query.execute()
            payouts_data = payouts_response.data if hasattr(payouts_response, 'data') else []
        except Exception as db_error:
            print(f"Database connection error for payouts: {db_error}")
            payouts_data = []
        
        # Calculate totals from valid earnings only
        total_earnings = sum(float(e.get('amount', 0)) for e in valid_earnings)
        total_payouts = sum(float(p.get('total_amount', 0)) for p in payouts_data)
        pending_payouts = sum(float(p.get('total_amount', 0)) for p in payouts_data if p.get('status') == 'pending')
        completed_payouts = sum(float(p.get('total_amount', 0)) for p in payouts_data if p.get('status') == 'completed')
        
        # Calculate cancellations if this is a sales report
        total_cancellations = 0
        cancelled_amount = 0
        if date_from and date_to:
            cancelled_earnings = [e for e in earnings_data if (e.get('status') or '').lower() == 'reversed']
            total_cancellations = len(cancelled_earnings)
            cancelled_amount = sum(float(e.get('amount', 0)) for e in cancelled_earnings)
        
        # Summary section - Dynamic based on report type
        if date_from and date_to:
            elements.append(Paragraph("Sales Summary", section_style))
        else:
            elements.append(Paragraph("Financial Summary", section_style))
        
        # Add date range info if applicable
        if start_date and end_date:
            date_range_text = f"Report Period: {start_date.strftime('%B %d, %Y')} to {end_date.strftime('%B %d, %Y')}"
            date_style = ParagraphStyle('DateRange', parent=styles['Normal'], fontSize=10, textColor=colors.HexColor('#666666'), spaceAfter=4*mm)
            elements.append(Paragraph(date_range_text, date_style))
        
        # Build summary data based on report type
        if date_from and date_to:
            # Sales report summary
            total_bookings = len(valid_earnings)
            avg_per_booking = total_earnings / total_bookings if total_bookings > 0 else 0
            summary_data = [
                ['Total Sales', f'PHP {total_earnings:,.2f}'],
                ['Total Bookings', f'{total_bookings:,}'],
                ['Average per Booking', f'PHP {avg_per_booking:,.2f}'],
                ['Cancellations', f'{total_cancellations:,}'],
                ['Lost Revenue (Cancellations)', f'PHP {cancelled_amount:,.2f}'],
                ['Admin Revenue (20%)', f'PHP {total_earnings * 0.2:,.2f}'],
                ['Driver Revenue (80%)', f'PHP {total_earnings * 0.8:,.2f}']
            ]
        else:
            # Traditional earnings report summary
            summary_data = [
                ['Total System Earnings', f'PHP {total_earnings:,.2f}'],
                ['Total Driver Payouts', f'PHP {total_payouts:,.2f}'],
                ['Pending Payouts', f'PHP {pending_payouts:,.2f}'],
                ['Completed Payouts', f'PHP {completed_payouts:,.2f}'],
                ['Admin Revenue (20%)', f'PHP {total_earnings * 0.2:,.2f}']
            ]
        
        summary_table = Table(summary_data, colWidths=[100*mm, 50*mm])
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#F8F9FA')),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#2C3E50')),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 11),
            ('ROWBACKGROUNDS', (0, 0), (-1, -1), [colors.white, colors.HexColor('#F8F9FA')]),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E9ECEF')),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8)
        ]))
        
        elements.append(summary_table)
        elements.append(Spacer(1, 8*mm))
        
        # Add grouped sales data if this is a sales report (skip API call to avoid connection issues)
        if date_from and date_to and group_by and valid_earnings:
            try:
                # Generate grouped data directly from earnings data instead of API call
                from collections import defaultdict
                
                grouped_data = defaultdict(lambda: {'sales': 0, 'bookings': 0, 'cancellations': 0})
                
                for earning in earnings_data:
                    try:
                        earning_date = datetime.fromisoformat(earning.get('earning_date', '').replace('Z', '+00:00'))
                        
                        if group_by == 'daily':
                            key = earning_date.strftime('%Y-%m-%d')
                        elif group_by == 'weekly':
                            week_start = earning_date - timedelta(days=earning_date.weekday())
                            key = f"Week of {week_start.strftime('%b %d, %Y')}"
                        elif group_by == 'monthly':
                            key = earning_date.strftime('%B %Y')
                        elif group_by == 'yearly':
                            key = earning_date.strftime('%Y')
                        else:
                            key = earning_date.strftime('%Y-%m-%d')
                        
                        amount = float(earning.get('amount', 0))
                        status = (earning.get('status') or '').lower()
                        
                        if status == 'reversed':
                            grouped_data[key]['cancellations'] += 1
                        else:
                            grouped_data[key]['sales'] += amount
                            grouped_data[key]['bookings'] += 1
                    except (ValueError, TypeError):
                        continue
                
                if grouped_data:
                    elements.append(Paragraph(f"Sales Breakdown by {group_by.title()}", section_style))
                    
                    # Create grouped data table
                    grouped_table_data = [['Period', 'Sales (PHP)', 'Bookings', 'Avg per Booking', 'Cancellations']]
                    
                    for period, data in sorted(grouped_data.items()):
                        sales_amt = data['sales']
                        bookings_count = data['bookings']
                        cancels = data['cancellations']
                        avg_booking = sales_amt / bookings_count if bookings_count > 0 else 0
                        
                        grouped_table_data.append([
                            str(period),
                            f'PHP {sales_amt:,.2f}',
                            str(bookings_count),
                            f'PHP {avg_booking:,.2f}',
                            str(cancels)
                        ])
                    
                    grouped_table = Table(grouped_table_data, colWidths=[40*mm, 35*mm, 25*mm, 30*mm, 20*mm])
                    grouped_table.setStyle(TableStyle([
                        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2E86AB')),
                        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
                        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                        ('FONTSIZE', (0, 0), (-1, 0), 10),
                        ('FONTSIZE', (0, 1), (-1, -1), 9),
                        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8F9FA')]),
                        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#DEE2E6')),
                        ('TOPPADDING', (0, 0), (-1, -1), 6),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 6)
                    ]))
                    
                    elements.append(grouped_table)
                    elements.append(Spacer(1, 8*mm))
            except Exception as e:
                print(f"Failed to add grouped sales data: {e}")
                pass
        
        # Earnings details section - Dynamic based on report type
        if date_from and date_to:
            elements.append(Paragraph("Sales Details", section_style))
            earnings_table_data = [['Driver Name', 'Booking ID', 'Amount', 'Status', 'Date']]
            display_earnings = sorted(valid_earnings, key=lambda x: x.get('earning_date', ''), reverse=True)[:30]
        else:
            elements.append(Paragraph("Recent Earnings Details", section_style))
            earnings_table_data = [['Driver Name', 'Booking ID', 'Amount', 'Status', 'Date']]
            display_earnings = sorted(valid_earnings, key=lambda x: x.get('earning_date', ''), reverse=True)[:20]
        
        for earning in display_earnings:
            earnings_table_data.append([
                earning.get('driver_name', 'N/A'),
                earning.get('booking_id', 'N/A')[:8] + '...' if earning.get('booking_id') else 'N/A',
                f"PHP {float(earning.get('amount', 0)):,.2f}",
                earning.get('status', 'N/A').title(),
                earning.get('earning_date', 'N/A')[:10] if earning.get('earning_date') else 'N/A'
            ])
        
        earnings_table = Table(earnings_table_data, colWidths=[40*mm, 30*mm, 30*mm, 25*mm, 25*mm])
        earnings_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2E86AB')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('ALIGN', (2, 0), (2, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8F9FA')]),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#DEE2E6')),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6)
        ]))
        
        elements.append(earnings_table)
        elements.append(Spacer(1, 8*mm))
        
        # Payout status
        elements.append(Paragraph("Payout Status Overview", section_style))
        
        payout_table_data = [['Driver Name', 'Total Amount', 'Status', 'Method', 'Date']]
        
        for payout in payouts_data[:15]:
            payout_table_data.append([
                payout.get('driver_name', 'N/A'),
                f"PHP {float(payout.get('total_amount', 0)):,.2f}",
                payout.get('status', 'N/A').title(),
                payout.get('payout_method', 'N/A').title(),
                payout.get('payout_date', 'N/A')[:10] if payout.get('payout_date') else 'N/A'
            ])
        
        payout_table = Table(payout_table_data, colWidths=[40*mm, 30*mm, 25*mm, 25*mm, 30*mm])
        payout_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#A23B72')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8F9FA')]),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#DEE2E6')),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6)
        ]))
        
        elements.append(payout_table)
        
    except Exception as e:
        error_style = ParagraphStyle('Error', parent=styles['Normal'], fontSize=12, textColor=colors.red)
        elements.append(Paragraph(f"Error generating report: {str(e)}", error_style))
    
    # Footer
    elements.append(Spacer(1, 10*mm))
    footer_style = ParagraphStyle('Footer', parent=styles['Normal'], fontSize=8, textColor=colors.HexColor('#6C757D'), alignment=TA_CENTER)
    elements.append(Paragraph("This report is confidential and intended for administrative use only.", footer_style))
    elements.append(Paragraph("© 2024 Tartanilla Tourism Management System. All rights reserved.", footer_style))
    
    # Build with page numbers
    def add_page_number(canvas, doc):
        canvas.saveState()
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(colors.HexColor('#6C757D'))
        canvas.drawRightString(A4[0] - 30*mm, 15*mm, f"Page {canvas.getPageNumber()}")
        canvas.drawString(30*mm, 15*mm, "Tartanilla Tourism Management System")
        canvas.restoreState()
    
    doc.title = filename
    doc.build(elements, onFirstPage=add_page_number, onLaterPages=add_page_number)
    
    # Log to audit trail (with connection error handling)
    try:
        admin_email = request.COOKIES.get('admin_email', 'Unknown Admin')
        admin_id = request.COOKIES.get('admin_user_id', 'Unknown')
        
        audit_data = {
            'user_id': admin_id,
            'username': admin_email,
            'role': 'admin',
            'action': 'SALES_PDF_EXPORT' if (date_from and date_to) else 'PDF_EXPORT',
            'entity_name': 'SALES_REPORT' if (date_from and date_to) else 'EARNINGS_REPORT',
            'entity_id': 'sales_report' if (date_from and date_to) else 'earnings_revenue',
            'new_data': {
                'report_type': 'sales_report' if (date_from and date_to) else 'earnings_revenue',
                'filename': filename,
                'period': period,
                'period_label': period_label,
                'date_from': date_from,
                'date_to': date_to,
                'group_by': group_by,
                'total_earnings': total_earnings if 'total_earnings' in locals() else 0,
                'total_bookings': len(valid_earnings) if 'valid_earnings' in locals() and (date_from and date_to) else None,
                'timestamp': datetime.now().isoformat()
            },
            'ip_address': request.META.get('REMOTE_ADDR', 'Unknown')
        }
        
        try:
            supabase.table('audit_logs').insert(audit_data).execute()
        except Exception as audit_error:
            print(f"Failed to insert audit log (connection issue): {audit_error}")
    except Exception as e:
        print(f"Failed to prepare audit log: {e}")
    
    return response