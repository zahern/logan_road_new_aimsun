      subroutine ramp_metering(t)
c --
c -- This subroutine is to calculate the rate of the metered ramp
c --
c -- This subroutine is called from loop
c -- This subroutine does not call any other subroutines
c --
c -- INPUT:
c --  t: current clock time
c -- OUTPUT:
c --  The adjusted saturation flow of the ramp.
c -- 
	use muc_mod
c  --
      do i=1,dec_num

       if(t.ge.ramp_start(i).and.t.le.ramp_end(i)) then
	 link_number=det_link(i)
	 link_ramp=detector_ramp(i)
         occup(i)=occup(i)/detector_length(i)
         occup(i)=occup(i)/(nlanes(link_number)*nrate/tii)           

!	   MaxFlowRate(link_ramp)=
!     +  (MaxFlowRate(link_ramp)/nlanes(link_ramp))+ramp_par(i,1)*
!     +       (ramp_par(i,2)-occup(i))
!         MaxFlowRate(link_ramp)=nlanes(link_ramp)*MaxFlowRate(link_ramp)
!         sattmp=ramp_par(i,3)*nlanes(link_ramp)
!       if(MaxFlowRate(link_ramp).gt.sattmp)MaxFlowRate(link_ramp)=sattmp
!       if(MaxFlowRate(link_ramp).lt.0.08) MaxFlowRate(link_ramp)=0.08




	   MaxFlowRateOrig(link_ramp)=
     +  (MaxFlowRateOrig(link_ramp)/nlanes(link_ramp))+ramp_par(i,1)*
     +       (ramp_par(i,2)-occup(i))
      MaxFlowRateOrig(link_ramp)=nlanes(link_ramp)*
     +       MaxFlowRateOrig(link_ramp)
         sattmp=ramp_par(i,3)*nlanes(link_ramp)
       if(MaxFlowRateOrig(link_ramp).gt.sattmp) then
	 MaxFlowRateOrig(link_ramp)=sattmp
	 endif

       if(MaxFlowRateOrig(link_ramp).lt.0.08) then
	 MaxFlowRateOrig(link_ramp)=0.08
	 endif


       endif
         occup(i)=0.0
      enddo
c --
c --
c --   
      return
      end





