// Handle goods & services violation form
const goodsServicesForm = document.getElementById('goodsServicesForm');
if (goodsServicesForm) {
    goodsServicesForm.addEventListener('submit', function(e) {
        e.preventDefault();
        
        const formData = new FormData(this);
        const decision = formData.get('decision');
        const notes = formData.get('admin_notes');
        const suspensionDays = formData.get('suspension_days');
        
        if (!decision || !notes.trim()) {
            showErrorModal('Please select a decision and provide admin notes.');
            return;
        }
        
        const confirmMessage = decision === 'approve' 
            ? `Are you sure you want to APPROVE this violation?\n\nThis will:\n- Delete the post\n- Suspend the user for ${suspensionDays} days`
            : 'Are you sure you want to REJECT this report?\n\nNo action will be taken.';
        
        currentFormData = {
            decision: decision,
            admin_notes: notes,
            suspension_days: suspensionDays
        };
        
        showConfirmModal(confirmMessage);
    });
}

// Override confirm button handler for goods services
const originalConfirmHandler = document.getElementById('confirmBtn').onclick;
document.getElementById('confirmBtn').addEventListener('click', function() {
    if (goodsServicesForm && currentFormData && currentFormData.decision) {
        closeConfirmModal();
        
        const submitBtn = goodsServicesForm.querySelector('button[type="submit"]');
        const originalText = submitBtn.innerHTML;
        submitBtn.disabled = true;
        submitBtn.innerHTML = 'Processing...';
        
        const reportId = document.querySelector('[data-report-id]')?.getAttribute('data-report-id') || 
                        window.location.pathname.split('/').pop();
        
        const reviewData = {
            report_id: reportId,
            decision: currentFormData.decision,
            admin_notes: currentFormData.admin_notes,
            suspension_days: currentFormData.suspension_days
        };
        
        fetch('/api/reports/review_goods_services_violation/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]')?.value || ''
            },
            body: JSON.stringify(reviewData)
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                let message = data.message;
                if (data.post_deleted) {
                    message += '\n✓ Post has been deleted';
                }
                if (data.user_suspended) {
                    message += '\n✓ User has been suspended';
                }
                showSuccessModal(message);
            } else {
                showErrorModal('Error: ' + data.error);
                submitBtn.disabled = false;
                submitBtn.innerHTML = originalText;
            }
        })
        .catch(error => {
            console.error('Error:', error);
            showErrorModal('An error occurred while processing the decision.');
            submitBtn.disabled = false;
            submitBtn.innerHTML = originalText;
        });
    }
});
