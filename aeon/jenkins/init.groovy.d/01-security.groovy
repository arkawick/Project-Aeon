import jenkins.model.*
import hudson.security.*

def instance = Jenkins.getInstance()

// Create admin user admin/admin
def hudsonRealm = new HudsonPrivateSecurityRealm(false)
hudsonRealm.createAccount('admin', 'admin')
instance.setSecurityRealm(hudsonRealm)

// Full control once logged in; allow anonymous read for API
def strategy = new FullControlOnceLoggedInAuthorizationStrategy()
strategy.setAllowAnonymousRead(true)
instance.setAuthorizationStrategy(strategy)

instance.save()
println "[Aeon] Security configured: admin/admin"
