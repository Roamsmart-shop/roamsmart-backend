@app.route('/api/user/stats', methods=['GET'])
@token_required
def get_user_stats():
    """Get user statistics"""
    completed_orders = Order.query.filter_by(user_id=g.current_user.id, status='completed').count()
    total_spent = db.session.query(db.func.sum(Order.amount)).filter_by(
        user_id=g.current_user.id, status='completed'
    ).scalar() or 0
    
    # Get referral stats
    referrals = Referral.query.filter_by(referrer_id=g.current_user.id).count()
    referral_earnings = db.session.query(db.func.sum(Referral.reward_amount)).filter_by(
        referrer_id=g.current_user.id, status='completed'
    ).scalar() or 0
    
    return jsonify({
        'success': True,
        'data': {
            'user': {
                **g.current_user.to_dict(),
                'avatar_url': g.current_user.avatar_url  # Make sure this is included
            },
            'total_orders': completed_orders,
            'total_spent': float(total_spent),
            'wallet_balance': g.current_user.wallet_balance,
            'referral_code': g.current_user.referral_code,
            'referral_count': referrals,
            'referral_earnings': float(referral_earnings),
            'is_agent': g.current_user.is_agent and g.current_user.agent_approved
        }
    })