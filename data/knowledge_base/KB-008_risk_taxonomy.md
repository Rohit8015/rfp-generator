# Risk Taxonomy & Mitigation Framework

## Risk Classification

### By Severity
| Level | Impact | Response Time | Escalation |
|-------|--------|---------------|------------|
| **Critical** | 25%+ project impact | Immediate | Steering Committee |
| **High** | 10-25% impact | 24 hours | Program Board |
| **Medium** | 5-10% impact | 72 hours | Project Manager |
| **Low** | <5% impact | 1 week | Team Lead |

### By Probability
- **Almost Certain**: >80% probability
- **Likely**: 50-80% probability
- **Possible**: 20-50% probability
- **Unlikely**: <20% probability

## Standard Programme Risks

### 1. Implementation Risks

#### Risk 1: Scope Creep
**Description**: Uncontrolled changes/additions to scope causing timeline and budget overrun
**Probability**: Likely
**Impact**: High
**Sensitivity**: High

**Mitigation**:
- Formal change control process with steering committee
- Regular scope validation during governance reviews
- 10% contingency for reasonable changes
- Include in assumptions: changes outside scope require change order

#### Risk 2: Resource Attrition
**Description**: Key project resources leaving during critical phases
**Probability**: Possible
**Impact**: High
**Sensitivity**: High

**Mitigation**:
- Knowledge management and documentation
- Cross-training and backup resources
- Retention incentives for key personnel
- 30-day replacement guarantee
- 15% bench strength maintained

#### Risk 3: Technical Debt/Legacy Integration
**Description**: Integration with legacy systems is more complex than anticipated
**Probability**: Likely
**Impact**: High
**Sensitivity**: High

**Mitigation**:
- Comprehensive discovery and integration assessment
- Phased integration approach with fallback
- Dedicated legacy integration team
- Automated testing for integration points
- Detailed API documentation and versioning

#### Risk 4: Data Migration Complexity
**Description**: Data quality issues, volume, or migration failures
**Probability**: Likely
**Impact**: Medium
**Sensitivity**: High

**Mitigation**:
- Data quality assessment and cleansing
- Phased migration with dry runs
- Data validation and reconciliation
- Rollback plan for each migration batch
- Close collaboration with client data team

#### Risk 5: Testing & Go-Live Issues
**Description**: Defects discovered during UAT or post go-live
**Probability**: Possible
**Impact**: High
**Sensitivity**: High

**Mitigation**:
- Comprehensive test strategy and automation
- Multiple UAT cycles
- Hyper-care support period
- Phased rollout to reduce risk
- Regular go-live drills

### 2. Technology Risks

#### Risk 6: Emerging Technology Immaturity
**Description**: New technologies fail to deliver expected outcomes
**Probability**: Possible
**Impact**: Medium
**Sensitivity**: Medium

**Mitigation**:
- Proof-of-concept before implementation
- Choose mature technologies where possible
- Have fallback options
- Partner with technology vendors for support
- Thorough technology due diligence

#### Risk 7: Performance Issues
**Description**: System doesn't meet performance requirements at scale
**Probability**: Possible
**Impact**: High
**Sensitivity**: High

**Mitigation**:
- Performance testing from early phases
- Scalability architecture design
- Monitoring and auto-scaling
- Capacity planning
- Performance optimization sprints

#### Risk 8: Security Vulnerabilities
**Description**: Security weaknesses exploited by attackers
**Probability**: Unlikely
**Impact**: Critical
**Sensitivity**: High

**Mitigation**:
- Secure SDLC integrated throughout
- Regular security testing (SAST, DAST, penetration)
- Security architecture review
- Continuous monitoring
- Incident response plan

### 3. Business Risks

#### Risk 9: Stakeholder Alignment
**Description**: Client stakeholders not aligned on priorities or decisions
**Probability**: Likely
**Impact**: Medium
**Sensitivity**: High

**Mitigation**:
- Clear RACI matrix
- Regular stakeholder mapping
- Monthly steering committee meetings
- Executive sponsor engagement
- Communication plan with regular updates

#### Risk 10: Regulatory Compliance
**Description**: New regulations or compliance changes impact project
**Probability**: Unlikely
**Impact**: High
**Sensitivity**: Medium

**Mitigation**:
- Regulatory mapping and monitoring
- Embed compliance in design
- Flexible architecture to adapt
- Regular legal reviews
- Contingency for regulatory changes

#### Risk 11: Business Case Not Met
**Description**: Project doesn't deliver expected ROI/business benefits
**Probability**: Possible
**Impact**: High
**Sensitivity**: High

**Mitigation**:
- Clear success metrics defined at start
- Baseline measurement before project
- Regular benefits tracking
- Quick wins in early phases
- Continuous business validation

#### Risk 12: Change Adoption
**Description**: Users resist new systems/processes
**Probability**: Likely
**Impact**: High
**Sensitivity**: High

**Mitigation**:
- Comprehensive change management program
- Early and frequent communication
- User involvement in design
- Training and support
- Champions program for adoption
- Measure and address adoption metrics

### 4. Vendor/Partner Risks

#### Risk 13: Subcontractor Failure
**Description**: Subcontractor fails to deliver quality or timeline
**Probability**: Unlikely
**Impact**: Medium
**Sensitivity**: High

**Mitigation**:
- Due diligence and reference checks
- Performance-based contracts
- Regular performance monitoring
- Exit and transition plan
- Multiple subcontractor options

#### Risk 14: Third-Party Dependency
**Description**: Vendor APIs/systems not available as expected
**Probability**: Possible
**Impact**: Medium
**Sensitivity**: High

**Mitigation**:
- Early engagement with third parties
- Service agreements with SLAs
- API monitoring and fallback
- Alternative solutions identified
- Contingency in schedule

### 5. Project Management Risks

#### Risk 15: Schedule Overrun
**Description**: Project exceeds the planned timeline
**Probability**: Likely
**Impact**: Medium
**Sensitivity**: High

**Mitigation**:
- Realistic estimation and planning
- 15% schedule contingency
- Regular progress tracking
- Critical path management
- Early warning system

#### Risk 16: Cost Overrun
**Description**: Project exceeds the planned budget
**Probability**: Possible
**Impact**: High
**Sensitivity**: High

**Mitigation**:
- Accurate estimation methodology
- 10% budget contingency
- Regular financial tracking
- Scope management
- Value engineering

#### Risk 17: Communication Gap
**Description**: Miscommunication between teams causes delays
**Probability**: Likely
**Impact**: Medium
**Sensitivity**: High

**Mitigation**:
- Communication plan and governance
- Weekly status meetings
- Dashboard reporting
- One-team culture (no vendor-client barrier)
- Joint workshops and planning

## Risk Response Strategies

### Mitigation Strategies
1. **Avoid**: Change approach to eliminate risk (e.g., use proven technology)
2. **Transfer**: Shift risk to third party (e.g., insurance, warranties)
3. **Mitigate**: Reduce probability/impact (e.g., testing, training)
4. **Accept**: Acknowledge risk and have contingency (e.g., schedule buffer)

### Risk Response for Critical Risks

| Risk ID | Response | Owner | Timeline |
|---------|----------|-------|----------|
| R-1 Scope Creep | Formal change control | PMO | Throughout |
| R-2 Attrition | Retention program | HR | Monthly |
| R-3 Legacy Integration | Phased approach | Tech Arch | Discovery |
| R-4 Data Migration | Phased with dry runs | Data Lead | Migration |
| R-5 Go-Live Issues | Hyper-care | PMO | Go-live |
| R-6 Tech Failure | POC + fallback | Tech Lead | Design |
| R-7 Performance Issues | Early performance testing | QA Lead | Build |
| R-8 Security Vulnerabilities | Sec SDLC | CISO | Throughout |
| R-9 Stakeholder Alignment | Governance | PMO | Throughout |
| R-10 Regulatory Compliance | Legal review | Compliance | Design |
| R-11 Business Case | Benefits tracking | PMO | Throughout |
| R-12 Change Adoption | CM Program | CM Lead | Throughout |
| R-13 Subcontractor | Performance monitoring | Partner Mgmt | Throughout |
| R-14 Third-Party | SLAs | Integration | Design |
| R-15 Schedule Overrun | 15% buffer | PMO | Throughout |
| R-16 Cost Overrun | 10% buffer | Finance | Monthly |
| R-17 Communication | Communication plan | PMO | Throughout |

## Risk Register Template

```json
{
  "risk_id": "R-001",
  "category": "Implementation",
  "description": "Scope creep causing timeline overrun",
  "probability": "Likely",
  "impact": "High",
  "risk_score": 16,
  "mitigation": "Formal change control process",
  "owner": "PMO",
  "status": "Active",
  "last_reviewed": "2026-07-20",
  "next_review": "2026-07-27"
}