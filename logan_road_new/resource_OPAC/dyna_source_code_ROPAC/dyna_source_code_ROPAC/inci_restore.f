      subroutine inci_restore(ilink,seve)
c --
c -- This subroutine restores the tane.mile length and saturation flow
c -- rate to their original value.
c --
c -- This subroutine is called from inci_check after the incident is cleared.
c -- This subroutine does not call any subroutines. 
c --
c -- INPUT :
c --   ilink : the link on which the incident occured
c --   seve : severity of the incident
c --
c -- OUTPUT :
c --   Restored lane.mile length and sturation flow rate for link "ilink". 
c --
      use muc_mod 
c --
      if(seve.gt.0.999) seve = 0.999
      xl(ilink)=nlanes(ilink)*s(ilink)
      MaxFlowRate(ilink)=MaxFlowRate(ilink)/(1-seve)
      return
      end
