      subroutine inci_effect(i) 
c --
c -- This subroutine reduces the link lane.mile according to the incident
c -- severity.
c --
c -- This subroutine is called from inci_check
c -- This subroutine does not call any subroutines
c --
c -- INPUT :
c --   ilink : the link on which the incident occured
c --   seve : severity of the incident
c --
c -- OUTPUT :
c --   Reduced lane.mile length and sturation flow rate for link "ilink".
c --
      use muc_mod 
c --
      seve=inci(i,3)      
      ilink=incil(i)

      if(seve.gt.0.999) seve=0.999
       
         xl(ilink)=nlanes(ilink)*s(ilink)*(1-seve)
         MaxFlowRate(ilink)=MaxFlowRate(ilink)*(1-seve)
    
      return
      end
