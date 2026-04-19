import copy
import importlib.util
import random
from pathlib import Path

import streamlit as st

GAME_PATH = Path(__file__).with_name('CaseStudy.py')

spec = importlib.util.spec_from_file_location('casestudy_game', GAME_PATH)
game = importlib.util.module_from_spec(spec)
spec.loader.exec_module(game)

INITIAL_STATE = copy.deepcopy(game.state)


def reset_game(seed=None):
    # 🔥 FIX: use persistent state instead of clearing
    st.session_state.game_state = copy.deepcopy(INITIAL_STATE)
    game.state = st.session_state.game_state

    game.events.clear()
    if seed is not None and seed != '':
        random.seed(int(seed))
    st.session_state.phase = 'quarter_choice'
    st.session_state.pending_events = []
    st.session_state.current_event = None
    st.session_state.history = []
    st.session_state.last_summary = ''
    st.session_state.game_over = False
    st.session_state.seed = seed


def money(x):
    return f"${x:,.0f}"


def pct(x):
    return f"{x*100:.0f}%"


def log(msg):
    st.session_state.history.append(msg)


def choose_install():
    inst = game.TUNING['INSTALL']['buy']
    game.apply_delta(inst)
    game.clamp_state()
    log(f"Installed da Vinci system: {inst['label']} ({game.money_delta(inst['budget'])}).")


def choose_training(option_key):
    opts = game.TUNING['TRAINING_OPTIONS']
    if option_key in ('1', '2', '3'):
        delta = opts[option_key]
        game.apply_delta(delta)
        if 'legal_risk_mult' in delta:
            game.state['legal_risk'] *= delta['legal_risk_mult']
        game.clamp_state()
        log(f"Training selected: {delta['label']} ({game.money_delta(delta['budget'])}).")
    else:
        if game.state['installed']:
            delta = opts['none']
            game.apply_delta(delta)
            game.clamp_state()
        log('Training skipped.')


def choose_marketing(run_marketing: bool):
    if not run_marketing:
        log('Chose to continue without added marketing.')
        return
    m = game.TUNING['MARKETING']
    for k in ('budget', 'cases_per_month', 'media_heat', 'adverse_pressure'):
        if k in m:
            game.state[k] += float(m[k])
    if game.state['training_level'] < m['training_threshold_unready']:
        game.state['reputation'] += m['reputation_if_unready']
        game.state['media_heat'] += m['media_heat_if_unready']
        game.state['adverse_pressure'] += m['adverse_pressure_if_unready']
        log('Marketing was launched while undertrained, increasing scrutiny.')
    game.clamp_state()
    log(f"Marketing executed ({game.money_delta(m['budget'])}).")


def advance_quarter():
    game.quarterly_operations()
    game.random_events_quarter()
    st.session_state.pending_events = game.pop_all_events()
    st.session_state.phase = 'event' if st.session_state.pending_events else 'post_quarter'
    if st.session_state.pending_events:
        st.session_state.current_event = st.session_state.pending_events.pop(0)
    else:
        st.session_state.current_event = None


def apply_malfunction_response(severity, response_key):
    impacts = game.TUNING['MALFUNCTION_IMPACTS'][severity]
    game.apply_delta(impacts)
    resp = game.TUNING['MALFUNCTION_RESPONSE'][response_key]
    game.apply_delta({k: v for k, v in resp.items() if k in game.state and not k.endswith('_mult')})
    game.apply_mult(resp)
    if 'legal_risk_mult' in resp:
        game.state['legal_risk'] *= resp['legal_risk_mult']
    game.clamp_state()
    log(f"Event: {severity.title()} malfunction. Response: {resp['label']}.")


def apply_pr_response(response_key):
    imp = game.TUNING['PR_BOOST_IMPACTS']
    game.apply_delta(imp)
    bonus = random.randint(game.TUNING['PR_BOOST_CASES_BONUS']['min'], game.TUNING['PR_BOOST_CASES_BONUS']['max'])
    game.state['cases_per_month'] += bonus

    chosen = game.TUNING['PR_RESPONSE'][response_key]
    game.state['budget'] += float(chosen.get('budget', 0.0))
    lo, hi = chosen.get('cases_bonus_range', (0, 0))
    if hi > 0:
        game.state['cases_per_month'] += random.randint(int(lo), int(hi))
    game.apply_delta({k: v for k, v in chosen.items() if k in game.state and not k.endswith('_mult') and k != 'budget'})
    game.apply_mult(chosen)
    if 'legal_risk_mult' in chosen:
        game.state['legal_risk'] *= chosen['legal_risk_mult']
    if response_key == '2':
        thresh = chosen.get('unready_training_threshold', 60.0)
        if game.state['training_level'] < thresh:
            game.state['reputation'] += chosen.get('reputation_if_unready', -4)
            game.state['media_heat'] += chosen.get('media_heat_if_unready', +0.12)
            game.state['adverse_pressure'] += chosen.get('adverse_pressure_if_unready', +0.10)
            log('Big marketing push after PR happened before the team was fully ready.')
    game.clamp_state()
    log(f"Event: PR boost. Response: {chosen['label']}.")


def apply_lawsuit_response(payout, response_key):
    L = game.TUNING['LAWSUIT']
    if response_key == '1':
        legal_fees = random.randint(L['legal_fees_min'], L['legal_fees_max'])
        game.state['budget'] -= legal_fees
        strength = (
            0.40 * (game.state['training_level'] / 100.0) +
            0.40 * (game.state['patient_safety'] / 100.0) +
            0.20 * (game.state['reputation'] / 100.0)
        )
        win_prob = game.clamp(L['win_prob_base'] + L['win_prob_scale'] * strength, 0.12, 0.80)
        if random.random() < win_prob:
            game.state['reputation'] += 2
            game.state['media_heat'] *= 0.86
            game.state['adverse_pressure'] *= 0.88
            game.state['legal_risk'] *= 0.90
            log('Event: Lawsuit fought successfully.')
        else:
            game.state['budget'] -= payout
            game.state['reputation'] -= 22
            game.state['patient_safety'] -= 10
            game.state['media_heat'] += 0.40
            game.state['adverse_pressure'] += 0.30
            game.state['legal_risk'] += 0.070
            log('Event: Lawsuit fight failed and went badly.')
    elif response_key == '2':
        settlement = int(payout * random.uniform(L['settle_frac_min'], L['settle_frac_max']))
        program_cost = random.randint(L['program_cost_min'], L['program_cost_max'])
        game.state['budget'] -= (settlement + program_cost)
        game.state['reputation'] -= 6
        game.state['patient_safety'] += 2
        game.state['media_heat'] *= 0.80
        game.state['adverse_pressure'] *= 0.78
        game.state['legal_risk'] *= 0.85
        log(f'Event: Lawsuit settled early for {money(settlement)} plus support costs.')
    elif response_key == '3':
        audit_cost = random.randint(L['audit_cost_min'], L['audit_cost_max'])
        residual = int(payout * random.uniform(L['residual_frac_min'], L['residual_frac_max']))
        game.state['budget'] -= (audit_cost + residual)
        game.state['reputation'] -= 10
        game.state['training_level'] += 8
        game.state['patient_safety'] += 6
        game.state['media_heat'] *= 0.78
        game.state['adverse_pressure'] *= 0.70
        game.state['legal_risk'] *= 0.83
        log(f'Event: Audit and improvement plan launched; residual settlement {money(residual)}.')
    else:
        game.state['reputation'] -= 14
        game.state['media_heat'] += 0.45
        game.state['adverse_pressure'] += 0.30
        game.state['legal_risk'] += 0.090
        log('Event: Lawsuit was stonewalled, increasing scrutiny.')

    game.state['media_heat'] += L['always_media_heat']
    game.state['legal_risk'] *= L['always_legal_risk_mult']
    game.clamp_state()


def maybe_low_rep_response(choice_key=None):
    if game.state['reputation'] >= 40:
        return
    if not choice_key:
        st.session_state.phase = 'low_rep'
        return
    chosen = game.TUNING['LOW_REP_RESPONSE'][choice_key]
    game.apply_delta({k: v for k, v in chosen.items() if k in game.state and not k.endswith('_mult')})
    game.apply_mult(chosen)
    if 'legal_risk_mult' in chosen:
        game.state['legal_risk'] *= chosen['legal_risk_mult']
    if 'media_heat' in chosen:
        game.state['media_heat'] += chosen['media_heat']
    if 'adverse_pressure' in chosen:
        game.state['adverse_pressure'] += chosen['adverse_pressure']
    if 'legal_risk' in chosen:
        game.state['legal_risk'] += chosen['legal_risk']
    game.clamp_state()
    log(f"Low-reputation response: {chosen['label']}.")
    st.session_state.phase = 'post_quarter'


def finish_post_quarter():
    if game.check_end_conditions():
        st.session_state.game_over = True
        st.session_state.phase = 'game_over'
        return
    game.state['month'] += game.STEP_MONTHS
    st.session_state.phase = 'quarter_choice'


def progress_after_event():
    if st.session_state.pending_events:
        st.session_state.current_event = st.session_state.pending_events.pop(0)
        st.session_state.phase = 'event'
    else:
        st.session_state.current_event = None
        maybe_low_rep_response()
        if st.session_state.phase != 'low_rep':
            st.session_state.phase = 'post_quarter'


def render_metrics():
    s = game.state
    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(f"""
<div style="font-size: 0.9rem; color: rgba(49, 51, 63, 0.6);">Budget</div>
<div style="font-size: 2rem; font-weight: 600;">{money(s['budget'])}</div>
""", unsafe_allow_html=True)
    c2.metric('Reputation', f"{s['reputation']:.0f}/100")
    c3.metric('Patient safety', f"{s['patient_safety']:.0f}/100")
    c4.metric('Training', f"{s['training_level']:.0f}/100")
    c5, c6, c7, c8 = st.columns(4)
    c5.metric('Monthly cases', f"{s['cases_per_month']}")
    c6.metric('Installed', 'Yes' if s['installed'] else 'No')
    c7.metric('Adverse pressure', pct(s['adverse_pressure']))
    c8.metric('Media heat', pct(s['media_heat']))
    st.caption(f"Month {s['month']:02.0f} • Quarter {game.quarter_number()} • Legal risk {pct(s['legal_risk'])}")


def render_sidebar():
    st.sidebar.header('Game controls')
    seed_value = st.sidebar.text_input('Random seed (optional)', value=st.session_state.get('seed', '') or '')
    if st.sidebar.button('New game', use_container_width=True):
        reset_game(seed_value or None)
        st.rerun()
    st.sidebar.markdown('This UI leaves **CaseStudy.py** untouched and uses it as the simulation engine.')


def init_session():
    if 'phase' not in st.session_state:
        reset_game()

    # 🔥 FIX: persist + rebind state every run
    if "game_state" not in st.session_state:
        st.session_state.game_state = copy.deepcopy(INITIAL_STATE)

    game.state = st.session_state.game_state


st.set_page_config(page_title='Hospital Admin UI', page_icon='🏥', layout='wide')
init_session()
render_sidebar()

st.title('Hospital Admin: da Vinci Adoption')
render_metrics()

with st.expander('Quarter log', expanded=True):
    if st.session_state.history:
        for item in reversed(st.session_state.history[-12:]):
            st.write(f'- {item}')
    else:
        st.write('No actions yet.')

phase = st.session_state.phase

if phase == 'quarter_choice':
    if not game.state['installed']:
        st.subheader('Install the system')
        inst = game.TUNING['INSTALL']['buy']
        st.info(f"{inst['label']} — {game.money_delta(inst['budget'])}")
        if st.button('Purchase and continue', type='primary'):
            choose_install()
            st.rerun()
    else:
        st.subheader('Quarterly decisions')
        train_col, market_col, nothing_col = st.columns(3)
        with train_col:
            st.markdown('**Training**')
            training_choice = st.radio(
                'Choose a training level',
                options=['1', '2', '3', 'skip'],
                format_func=lambda x: {
                    '1': 'Minimal', '2': 'Moderate', '3': 'Intensive', 'skip': 'Skip training'
                }[x],
                key='training_choice'
            )
        with market_col:
            st.markdown('**Marketing**')
            marketing = st.toggle('Increase marketing this quarter', value=False)
            st.caption('Higher volume can raise scrutiny if the team is not ready.')
        with nothing_col:
            st.markdown('**Advance**')
            st.write('Submit your quarter and let the simulation run.')
            if st.button('Run quarter', type='primary', use_container_width=True):
                choose_training(training_choice if training_choice != 'skip' else 'skip')
                choose_marketing(marketing)
                advance_quarter()
                st.rerun()

elif phase == 'event':
    evt = st.session_state.current_event
    evt_type = evt['type']
    st.subheader('Quarter event')

    if evt_type == 'malfunction':
        severity = evt['data'].get('severity', 'minor')
        st.warning(f"Device malfunction: **{severity.title()}**")
        response = st.radio(
            'Choose an operational response',
            options=['1', '2', '3'],
            format_func=lambda x: game.TUNING['MALFUNCTION_RESPONSE'][x]['label'],
            key=f'malf_{severity}_{len(st.session_state.history)}'
        )
        if st.button('Apply malfunction response', type='primary'):
            apply_malfunction_response(severity, response)
            progress_after_event()
            st.rerun()

    elif evt_type == 'pr_boost':
        st.success('High-profile success generated positive press.')
        response = st.radio(
            'How do you respond?',
            options=['1', '2', '3'],
            format_func=lambda x: game.TUNING['PR_RESPONSE'][x]['label'],
            key=f'pr_{len(st.session_state.history)}'
        )
        if st.button('Apply PR response', type='primary'):
            apply_pr_response(response)
            progress_after_event()
            st.rerun()

    elif evt_type == 'lawsuit':
        payout = int(evt['data'].get('payout', 2_000_000))
        st.error(f"Lawsuit filed. Worst-case payout exposure: {money(payout)}")
        response = st.radio(
            'Choose a response',
            options=['1', '2', '3', '4'],
            format_func=lambda x: {
                '1': 'Fight',
                '2': 'Early settlement + support',
                '3': 'Audit + improvements',
                '4': 'Stonewall / delay',
            }[x],
            key=f'lawsuit_{len(st.session_state.history)}'
        )
        if st.button('Apply lawsuit response', type='primary'):
            apply_lawsuit_response(payout, response)
            progress_after_event()
            st.rerun()

elif phase == 'low_rep':
    st.subheader('Reputation response required')
    st.warning('Reputation has fallen below 40. Choose a recovery strategy.')
    response = st.radio(
        'Select a response',
        options=['1', '2', '3'],
        format_func=lambda x: game.TUNING['LOW_REP_RESPONSE'][x]['label'],
        key=f'low_rep_{len(st.session_state.history)}'
    )
    if st.button('Apply reputation response', type='primary'):
        maybe_low_rep_response(response)
        st.rerun()

elif phase == 'post_quarter':
    st.subheader('Quarter complete')
    st.info('All events and follow-up decisions for this quarter are done.')
    if st.button('Continue to next quarter', type='primary'):
        finish_post_quarter()
        st.rerun()

elif phase == 'game_over':
    st.subheader('Game over')
    if game.state['budget'] <= 0:
        st.error('You ran out of funds.')
    elif game.state['patient_safety'] <= 20:
        st.error('Patient safety collapsed. Regulatory shutdown.')
    elif game.state['reputation'] <= 10:
        st.error('Reputation was destroyed. The board removed you.')
    else:
        st.success('You completed the full 24 months.')
    st.button('Start over', on_click=reset_game)