const goodsServicesForm = document.getElementById('goodsServicesForm');
if (goodsServicesForm) {
    goodsServicesForm.addEventListener('submit', function(e) {
        e.preventDefault();
        
        const decision = document.querySelector('input[name="decision"]:checked')?.value;
        const notes = document.getElementById('gs_notes').value.trim();
        const suspensionDays = document.getElementById('suspension_days').value;
        
        if (!decision || !notes) {
            alert('Please select a decision and provide notes');
            return;
        }
        
        const msg = decision === 'approve' 
            ? `Approve violation? Driver will be suspended for ${suspensionDays} days.`
            : 'Reject violation? No action will be taken.';
        
        if (!confirm(msg)) return;
        
        const reportId = window.location.pathname.split('/').pop();
        
        fetch('/api/reports/review_goods_services_violation/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]')?.value || ''
            },
            body: JSON.stringify({
                report_id: reportId,
                decision: decision,
                admin_notes: notes,
                suspension_days: suspensionDays
            })
        })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                alert(data.message);
                window.location.href = '/reports/';
            } else {
                alert('Error: ' + data.error);
            }
        })
        .catch(e => alert('Error: ' + e));
    });
}
