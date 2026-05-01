      subroutine adjust_saturation(ilink,MFRtmp,t,typeid)
c --
c -- This subroutine adjusts the saturation flow rate for through
c -- traffic due to the existance of left turning vehicles on the same  link
c --
c -- This subroutine is called from get_link_capacity 
c -- every simulation interval for each
c -- link that needs saturation adjustment.
c -- This subroutine does not call any other subroutines
c --
c -- INPUT
c --      ilink : current link
c --          t : current clock time
c --
c -- OUTPUT
c --       MFRtmp : adjusted saturation flow rate
c --
      use muc_mod
      use LinkList_mod

      integer typeid,k
      real MFRtmp
c --
c -- left_count is the number of vehicles on the current link which are
c -- making a left turn at the end of the link during the current simulation interval.
c --
      Select Case (typeid)

      case (1)  ! signalized/signed arterials
        left_count=0 
        p_mtxj_value=>LinkVehList(ilink)
        do while(associated(p_mtxj_value%next_veh))
        idveh=p_mtxj_value%veh
        if(idveh.gt.0)then
          if(qflag(idveh))then
             nexl=nexlink(idveh)
             do k=1,move(ilink,nu_mv+1)
                if(nexl.eq.llink(ilink,k))then
                  if(move(ilink,k).eq.1) left_count=left_count+1.0
                endif
             enddo
          endif
        endif
       p_mtxj_value=>p_mtxj_value%next_veh
      enddo   
c --
c -- plt : is the ratio of left turning vehicles to the total number of 
c -- vehicles on the link. 
c --
      if(volume(ilink).lt.1)then
           plt=0
      else
           plt=left_count/volume(ilink)
      endif
c --
c -- flt : is the adjustment factor for the saturation flow for through
c --       vehicles (flt<=1.0) due to the left turning vehicles on the same
c --       link.
c --       
c -- Since DYNASMART does not have lane representation, so the adjustment
c -- factor for left turns will be approximated 
c -- according to the 1998 HCM Table 9-12, case 1 (with LT bay), 4 (without LT bay). 
c -- NOTE : we are applying the adjustment for all lanes on the link 
c --       (i.e. not the shared lanes only).
c --
      
!      if(bay(ilink)) then

      if(bay(ilink).ge.1)then
        MFRtmp=MaxFlowRate(ilink)*0.95  
	 ! sat() here is the total saturation rate for all lanes
      else
        flt=1.0/(1.0+0.05*plt)
        MFRtmp=MaxFlowRate(ilink)*flt
      endif

      case (0) ! freeway in pcphpl unit

      MFRtmp=MaxFlowRate(ilink)

      end select 

      return
      end
	  