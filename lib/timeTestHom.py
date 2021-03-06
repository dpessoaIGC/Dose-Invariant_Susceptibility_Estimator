"""Compare the fit of the homogeneous and heterogeneous models to each group, independently. 

Parameters estimated:
(infection-related)
- p1hom: parameter of the homogeneous model for group 1
- p1het,a1,b1: parameters of the heterogeneous model for group 1
- p2hom: parameter of the homogeneous model for group 2
- p2het,a2,b2: parameters of the heterogeneous model for group 2
- eps: probability of ineffective challenge
(mortality-related)
- meanI: mean time to death of infected hosts
- sI: shape parameter of the distribution of time to death of infected hosts
- meanU: mean time to death from old-age (i.e. from uninfected hosts)
- sU: shape parameter of the distribution of time to death of old-age
- k: background probability of death, independent of infection or old-age

Assumptions:
- infected flies cannot outlive natural mortality (meanI<meanU)
- prior distributions for parameters governing natural mortality set from those estimated from control survival
"""

# Import libraries
from copy import deepcopy
import pickle, pymc as py, numpy as np, scipy as sc, scipy.special as sp, scipy.stats as st, pylab as pl, sys, importlib, shutil
import utils as ut
import modelFunctions as mf
import dataFunctions as df

class Model(mf.TimeModels,mf.DoseResponseModels):
    """ Compare the fit of the homogeneous and heterogeneous models to each group, independently. 

Initialize from scratch with Model.setup(), and from saved model with Model.savedModel(). 

Parameters estimated:
(infection-related)
* p - probability that a single virion will cause infection in a host of the first group
* a,b - shape parameters for the distribution of susceptibility of the second group compared to the first
* eps - probability of ineffective challenge
(mortality-related)
* meanI - mean time to death of infected hosts
* sI - shape parameter of the distribution of time to death of infected hosts
* meanU - mean time to death from old-age (i.e. from uninfected hosts)
* sU - shape parameter of the distribution of time to death of old-age
* k - background probability of death, independent of infection or old-age

(extra)
* Ig1dX, Ig2dX - estimated number of infected hosts from group 1 (or 2) when challenged with dose number X

Assumptions:
- infected flies cannot outlive natural mortality (meanI<meanU)
- prior distributions for parameters governing natural mortality set from those estimated from control survival

Possible plots (only after MCMC has been run):
- plotSurvival
- plotBeta
- plotDoseResponse
- plotPosterior
- plotBestDays
"""
    __defaultPrior__='priors_testHom'
    __defaultName__='_testHom'
    #~~~~~~~~~~~~~~~~~~~~~~~~~#
    #~~ Setting up the MCMC ~~#
    #~~~~~~~~~~~~~~~~~~~~~~~~~#    
    def __init__(self,data, priors, name, path, bRandomIni):
        """Returns a Model object, used to launch MCMC and process posterior distributions.

Input:
- data (ut.Data)
- priors (dict) - a dictionnary with a PYMC object for each parameter
- name (str) - descriptor for the MCMC results
- path (str) - path to folder where results should be saved
"""
        m=self
        # The following are the variables needed for plots
        m.vals=('ts','cdf1hom_ci','cdf2hom_ci','cdf1het_ci','cdf2het_ci','x2','pi1hom_ci','pi2hom_ci','pi1het_ci','pi2het_ci','pdfU','cdfU','pdfI1','pdfI2')
        super(Model,self).__init__(data,priors,name,path,bRandomIni)
    
    @ut.doc_inherit
    def likelihood_setup(self, bRandomIni):
        #~~ Saving variable names ~~
        m=self
        d=self.d
        m.parameters.extend(['I1hom%i'%i for i in range(sum(d.doses==0),len(d.doses))])
        m.parameters.extend(['I1het%i'%i for i in range(sum(d.doses==0),len(d.doses))])
        m.parameters.extend(['I2hom%i'%i for i in range(sum(d.doses==0),len(d.doses))])
        m.parameters.extend(['I2het%i'%i for i in range(sum(d.doses==0),len(d.doses))])
        super(Model,self).likelihood_setup(bRandomIni)
    
    def __lik_setup__(self):
        m=self
        d=m.d
        chgT=m.chgT
        iTd1=m.iTd1
        iTd2=m.iTd2
        zeroprob=0
        try:
            
            #~~ Other stochastic variables needed to calculate the likelihood ~~
            for di in range(0+sum(d.doses==0),len(d.doses)):
                setattr(m,'pi1_hom%i'%di, py.Lambda('pi1_hom%i'%di,lambda p=m.p1hom,eps=m.eps,idose=di: ut.pi_hom(d.doses[idose],p,eps)))
                setattr(m,'I1hom%i'%di,py.Binomial('I1hom%i'%di,n=d.nhosts1[di],p=getattr(m,'pi1_hom%i'%di)))
                setattr(m,'pi1_het%i'%di, py.Lambda('pi1_het%i'%di,lambda p=m.p1het,a=m.a1,b=m.b1,eps=m.eps,idose=di: ut.pi_het(d.doses[idose],p,a,b,eps)))
                setattr(m,'I1het%i'%di,py.Binomial('I1het%i'%di,n=d.nhosts1[di],p=getattr(m,'pi1_het%i'%di)))
                
                setattr(m,'pi2_hom%i'%di, py.Lambda('pi2_hom%i'%di,lambda p=m.p2hom,eps=m.eps,idose=di: ut.pi_hom(d.doses[idose],p,eps)))
                setattr(m,'I2hom%i'%di,py.Binomial('I2hom%i'%di,n=d.nhosts2[di],p=getattr(m,'pi2_hom%i'%di)))
                setattr(m,'pi2_het%i'%di, py.Lambda('pi2_het%i'%di,lambda p=m.p2het,a=m.a2,b=m.b2,eps=m.eps,idose=di: ut.pi_het(d.doses[idose],p,a,b,eps)))
                setattr(m,'I2het%i'%di,py.Binomial('I2het%i'%di,n=d.nhosts2[di],p=getattr(m,'pi2_het%i'%di)))            
                
            
            m.tauU=py.Lambda('tauU',lambda mean=m.meanU, s=m.sU: mean/s)
            m.tauI1=py.Lambda('tauI1',lambda mean=m.meanI1, s=m.sI1: mean/s)
            m.tauI2=py.Lambda('tauI2',lambda mean=m.meanI2, s=m.sI2: mean/s)
            
            
            #~~ Likelihood ~~
            
            # Calculate the probabilities of deaths at each of the changing times
            m.probdU=py.Lambda('probdU',lambda s=m.sU, tau=m.tauU, k=m.k,t1=d.times[chgT-1],t2=d.times[chgT]: ut.kpdfInt(t1,t2,s,tau,k), trace=False)
            m.probdI1=py.Lambda('probdI1',lambda s=m.sI1, tau=m.tauI1, k=m.k,t1=d.times[chgT-1],t2=d.times[chgT]: ut.kpdfInt(t1,t2,s,tau,k), trace=False)
            m.probdI2=py.Lambda('probdI2',lambda s=m.sI2, tau=m.tauI2, k=m.k,t1=d.times[chgT-1],t2=d.times[chgT]: ut.kpdfInt(t1,t2,s,tau,k), trace=False)
            
            # Calculate the probabilities of survival at each of the changing times
            m.probsU=py.Lambda('probsU',lambda s=m.sU, tau=m.tauU, k=m.k: 1-(ut.kpdfInt(0,d.tmax,s,tau,k)), trace=False)
            m.probsI1=py.Lambda('probsI1',lambda s=m.sI1, tau=m.tauI1, k=m.k: 1-(ut.kpdfInt(0,d.tmax,s,tau,k)), trace=False)
            m.probsI2=py.Lambda('probsI2',lambda s=m.sI2, tau=m.tauI2, k=m.k: 1-(ut.kpdfInt(0,d.tmax,s,tau,k)), trace=False)
            
            def likelihood_deaths(value,nf,I,probdI,probdU):
                res=(I/nf)*probdI[value]+(1-(I/nf))*probdU[value]
                inf0=res<0
                if any(inf0): 
                    res[res<0]=0
                return np.log(res).sum()
            
            def likelihood_survivors(value,nf,I,probsI,probsU):
                res=((I/nf)*probsI+(1-(I/nf))*probsU)**value
                inf0=res<0
                if inf0: 
                    res=0
                return np.log(res)
            
          
            # Calculate the likelihoods
            m.hom1liks=[]
            m.hom2liks=[]
            m.het1liks=[]
            m.het2liks=[]  
            for i in range(0+sum(d.doses==0),len(d.doses)):
                setattr(m,'LD1hom_d%i'%i,py.Stochastic(logp=likelihood_deaths,doc='',name='LD1hom_d%i'%i,parents={'nf':d.nhosts1[i], 'I':getattr(m,'I1hom%i'%i), 'probdI':m.probdI1,'probdU':m.probdU}, trace=False, observed=True, dtype=int, value=iTd1[i]))
                m.hom1liks+=['LD1hom_d%i'%i]
                
                setattr(m,'LD1het_d%i'%i,py.Stochastic(logp=likelihood_deaths,doc='',name='LD1het_d%i'%i,parents={'nf':d.nhosts1[i], 'I':getattr(m,'I1het%i'%i), 'probdI':m.probdI1,'probdU':m.probdU}, trace=False, observed=True, dtype=int, value=iTd1[i]))
                m.het1liks+=['LD1het_d%i'%i]
                
                if d.survivors1[i]>0:
                    setattr(m,'LS1hom_d%i'%i,py.Stochastic(logp=likelihood_survivors,doc='',name='LS1hom_d%i'%i,parents={'nf':d.nhosts1[i], 'I':getattr(m,'I1hom%i'%i), 'probsI':m.probsI1,'probsU':m.probsU}, trace=False, observed=True, dtype=int, value=d.survivors1[i]))
                    m.hom1liks+=['LS1hom_d%i'%i]
                    setattr(m,'LS1het_d%i'%i,py.Stochastic(logp=likelihood_survivors,doc='',name='LS1het_d%i'%i,parents={'nf':d.nhosts1[i], 'I':getattr(m,'I1het%i'%i), 'probsI':m.probsI1,'probsU':m.probsU}, trace=False, observed=True, dtype=int, value=d.survivors1[i]))
                    m.het1liks+=['LS1het_d%i'%i]
                
                setattr(m,'LD2hom_d%i'%i,py.Stochastic(logp=likelihood_deaths,doc='',name='LD2hom_d%i'%i,parents={'nf':d.nhosts2[i], 'I':getattr(m,'I2hom%i'%i), 'probdI':m.probdI2,'probdU':m.probdU}, trace=False, observed=True, dtype=int, value=iTd2[i]))
                m.hom2liks+=['LD2hom_d%i'%i]
                
                setattr(m,'LD2het_d%i'%i,py.Stochastic(logp=likelihood_deaths,doc='',name='LD2het_d%i'%i,parents={'nf':d.nhosts2[i], 'I':getattr(m,'I2het%i'%i), 'probdI':m.probdI2,'probdU':m.probdU}, trace=False, observed=True, dtype=int, value=iTd2[i]))
                m.het2liks+=['LD2het_d%i'%i] 
                
                if d.survivors2[i]>0:
                    setattr(m,'LS2hom_d%i'%i,py.Stochastic(logp=likelihood_survivors,doc='',name='LS2hom_d%i'%i,parents={'nf':d.nhosts2[i], 'I':getattr(m,'I2hom%i'%i), 'probsI':m.probsI2,'probsU':m.probsU}, trace=False, observed=True, dtype=int, value=d.survivors2[i]))
                    m.hom2liks+=['LS2hom_d%i'%i]
                    setattr(m,'LS2het_d%i'%i,py.Stochastic(logp=likelihood_survivors,doc='',name='LS2het_d%i'%i,parents={'nf':d.nhosts2[i], 'I':getattr(m,'I2het%i'%i), 'probsI':m.probsI2,'probsU':m.probsU}, trace=False, observed=True, dtype=int, value=d.survivors2[i]))
                    m.het2liks+=['LS2het_d%i'%i]
            
            # Set likelihood to 0 if, for the first group, there is higher chance of infected surviving to the end of the study compared to non-infected.
            @py.potential
            def potIdeaths1(sI=m.sI1,tauI=m.tauI1, sU=m.sU,tauU=m.tauU): 
                return 0.0 if st.gamma.cdf(max(d.times),sI,loc=0,scale=tauI)>=st.gamma.cdf(max(d.times),sU,loc=0,scale=tauU) else -np.Inf
            
            @py.potential
            def potIdeaths2(sI=m.sI2,tauI=m.tauI2, sU=m.sU,tauU=m.tauU): 
                return 0.0 if st.gamma.cdf(max(d.times),sI,loc=0,scale=tauI)>=st.gamma.cdf(max(d.times),sU,loc=0,scale=tauU) else -np.Inf        
        
            setattr(m,'potIdeaths1',potIdeaths1)
            setattr(m,'potIdeaths2',potIdeaths2)
            
            m.liks=m.hom1liks+m.hom2liks+m.het1liks+m.het2liks
            
            sum([getattr(m,l).logp for l in m.liks])+potIdeaths1.logp+potIdeaths2.logp
            
        except py.ZeroProbability:
            zeroprob=1
        return zeroprob
    
    #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~#
    #~~ Calculating posterior predictive distributions ~~#
    #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~#
    def __calc__(self):
        progBar=ut.ProgressBar("Preparing calculations of posterior probabilities")
        
        d=self.d
        for p in self.parameters:
            exec('%ss=self.%ss'%(p,p))
        tauUs=meanUs/sUs
        tauI1s=meanI1s/sI1s
        tauI2s=meanI2s/sI2s
        setattr(self,'tauUs',tauUs)
        setattr(self,'tauI1s',tauI1s)
        setattr(self,'tauI2s',tauI2s)        
        
        ts=np.arange(0,d.times[-1]+1,0.2)
        cdf1hom_ci=np.zeros([3,d.ndoses,len(ts)]) # Interval for the probability of death per dose at each day
        cdf1het_ci=np.zeros([3,d.ndoses,len(ts)])
        cdf2hom_ci=np.zeros([3,d.ndoses,len(ts)]) # Interval for the probability of death per dose at each day
        cdf2het_ci=np.zeros([3,d.ndoses,len(ts)])        
        
        #PDFs
        pdfI1=eval(ut.callArray('ut.kpdf(',['ts','sI1s','tauI1s','ks'],(len(ts),len(sUs))))
        progBar.iter(0.25)
        
        pdfI2=eval(ut.callArray('ut.kpdf(',['ts','sI2s','tauI2s','ks'],(len(ts),len(sUs))))
        progBar.iter(0.25)        
        
        #CDFs
        cdfU=eval(ut.callArray('ut.kpdfInt(0,',['ts','sUs','tauUs','ks'],(len(ts),len(sUs))))
        
        cdfI1=eval(ut.callArray('ut.kpdfInt(0,',['ts','sI1s','tauI1s','ks'],(len(ts),len(sUs))))
        progBar.iter(0.25)
        
        cdfI2=eval(ut.callArray('ut.kpdfInt(0,',['ts','sI2s','tauI2s','ks'],(len(ts),len(sUs))))
        progBar.iter(0.25)
        progBar.finish()
        
        progBar.start("Calculating mortalities")
        di=0
        
        cdf1hom_ci[:,0,:]=ut.confint(1-cdfU)
        cdf1het_ci[:,0,:]=ut.confint(1-cdfU)
        cdf2hom_ci[:,0,:]=ut.confint(1-cdfU)
        cdf2het_ci[:,0,:]=ut.confint(1-cdfU)        
        progBar.iter(1./d.ndoses)
        
        for di in range(1,d.ndoses):
            pi1homs=ut.pi_hom(d.doses[di],p1homs,epss)
            pi1hets=ut.pi_het(d.doses[di],p1hets,a1s,b1s,epss)
            
            cdf1hom_ci[:,di,:]=ut.confint(1-((np.array([pi1homs.tolist()]*len(ts)).T)*cdfI1)-((1-np.array([pi1homs.tolist()]*len(ts)).T)*cdfU))
            cdf1het_ci[:,di,:]=ut.confint(1-((np.array([pi1hets.tolist()]*len(ts)).T)*cdfI1)-((1-np.array([pi1hets.tolist()]*len(ts)).T)*cdfU))
            
            pi2homs=ut.pi_hom(d.doses[di],p2homs,epss)
            pi2hets=ut.pi_het(d.doses[di],p2hets,a1s,b1s,epss)
            
            cdf2hom_ci[:,di,:]=ut.confint(1-((np.array([pi2homs.tolist()]*len(ts)).T)*cdfI1)-((1-np.array([pi2homs.tolist()]*len(ts)).T)*cdfU))
            cdf2het_ci[:,di,:]=ut.confint(1-((np.array([pi2hets.tolist()]*len(ts)).T)*cdfI1)-((1-np.array([pi2hets.tolist()]*len(ts)).T)*cdfU))
            
            progBar.iter(1./d.ndoses)
            
        
        progBar.finish()
        progBar.start("Calculating probabilities of infection")
        
        x2=10**np.arange(np.log10(d.doses[d.doses>0][0])-1,np.log10(d.doses[-1])+1,0.1)
        pi1hom_ci=np.zeros([3,len(x2)])
        pi1het_ci=np.zeros([3,len(x2)])
        pi2hom_ci=np.zeros([3,len(x2)])
        pi2het_ci=np.zeros([3,len(x2)])
        for i in range(len(x2)):
            pi1hom_ci[:,i]=ut.confint(ut.pi_hom(x2[i],p1homs,epss))
            pi1het_ci[:,i]=ut.confint(ut.pi_het(x2[i],p1hets ,a1s,b1s,epss))
            pi2hom_ci[:,i]=ut.confint(ut.pi_hom(x2[i],p2homs,epss))
            pi2het_ci[:,i]=ut.confint(ut.pi_het(x2[i],p2hets ,a2s,b2s,epss))
            progBar.iter(1./len(x2))
        
        progBar.finish()
        
        pdfU=ut.confint(cdfU[:,1:]-cdfU[:,:-1]) # Calculate pdf from cdf to avoid nan from high sU, len= len(ts)-1
        cdfU=ut.confint(cdfU)
        pdfI1=ut.confint(pdfI1)
        pdfI2=ut.confint(pdfI2)
        
        res={'burnin':self.burnin,'thinF':self.thinF}
        for v in self.vals:
            setattr(self,v,eval(v))
            res[v]=eval(v)
        for v in self.parameters:
            res[v+'s']=eval(v+'s')
        pickle.dump(res,open(self.saveTo+'-postcalc.pickle','w'))
        
        self.__plot__()
    
    def __plot__(self):
        print "Results saved in "+self.path
        self.write_vals()
        self.plotSurvival()
        self.plotPosterior()
    
    def setgroup(self,i):
        """ Set variables for plotting group 1 (i=1) or group 2 (i=2).
If i=0, reset all variables. """
        if i==0:
            self.a2s=None
            self.b2s=None
            self.pi1_ci=None
            self.pi2_ci=None
            self.cdf1_ci=None
            self.cdf2_ci=None
        elif (i==1) or (i==2):
            self.a2s=getattr(self,'a%is'%i)
            self.b2s=getattr(self,'b%is'%i)
            self.pi1_ci=getattr(self,'pi%ihom_ci'%i)
            self.pi2_ci=getattr(self,'pi%ihet_ci'%i)
            self.cdf1_ci=getattr(self,'cdf%ihom_ci'%i)
            self.cdf2_ci=getattr(self,'cdf%ihet_ci'%i)
    
    def plotBeta(self):
        """Plots the estimated beta distribution for group 1 with confidence interval. (Same as panel B of Figure 5 of the article). """
        self.setgroup(1)
        res1 = super(Model,self).plotBeta('-Beta1',colors=self.colors[0]*2)
        
        self.setgroup(2)
        res2=super(Model,self).plotBeta('-Beta2',colors=self.colors[1]*2)
        
        self.setgroup(0)
        return res1,res2
    
    def plotDoseResponse(self):
        """ Plots the dose-response curve for group 1 with confidence intervals. (Same as panel A of Figure 5 in article)."""
        self.setgroup(1)
        res1=super(Model,self).plotDoseResponse('-DoseResponse1',colors=self.colors[0]*2)
        
        self.setgroup(2)
        res2=super(Model,self).plotDoseResponse('-DoseResponse2',colors=self.colors[1]*2)
        self.setgroup(0)
        return (res1,res2)
    
    def plotPosterior(self):
        """Plots the posterior intervals for the dose-response curve for group 1, the beta distribution of the heterogeneous model and the correlation between the parameters a and b from the beta distribution.
In solid line is the homogeneous model, in dashed line the heterogeneous model, both fitted to group 1.

Equivalent figure in article: Figure 3.

Returns:
- f: Figure
- ax1, ax2, ax3: Axes from each of the panels"""
        self.setgroup(1)
        res1=super(Model,self).plotPosterior(name='-plotPosterior1',colors=self.colors[0]*2)
        
        self.setgroup(2)
        res2=super(Model,self).plotPosterior(name='-plotPosterior2',colors=self.colors[1]*2)   
        self.setgroup(0)
        return res1,res2
    
    def plotSurvival(self):
        """Plots survival over time for each of the doses. 

One panel per dose, results from homogeneous and heterogeneous models superimposed. 
Full line is the homogeneous model, dashed line the heterogeneous model.
Group 1 in black, group 2 in blue. 

Equivalent figures in article: Figure S1.

Returns:
- f1,ax1 (Figure, Axes): Objects for group 1 
- f2,ax2 (Figure, Axes): Objects for group 2."""
        self.setgroup(1)
        res1=super(Model,self).plotSurvival(name='-plotSurvival1',colors=self.colors[0]*2, extra='for group 1')
        self.setgroup(2)
        res2=super(Model,self).plotSurvival(name='-plotSurvival2',colors=self.colors[1]*2, extra='for group 2')
        self.setgroup(0)
        return res1,res2

TimeData=df.TimeData
