	subroutine WZ_check(tt)
! -- This subroutine is the main subroutine for workzone simulation
! -- it checks the start and end of incidents 
! --
! -- This subroutine is called from loop every simulation interval.
! --
! -- This subroutine calls the following subroutines
! -- 2. WZ_effect
! -- 4. WZ_restore
! --
! -- INPUT :
! --    tt : current clock time
! --
! -- OUPUT : 
! --  No specific output.
! --
      	use muc_mod
! --
! -- If the work zone is starting during the current simulation interval,
! -- call WZ_add to add it to the list of active incidents.
! --
      	do i = 1, WorkZoneNum
         if(tt.ge.WorkZone(i)%ST.and.tt.lt.WorkZone(i)%ET) then
	     if(.not.wzstartflag(i)) then
             wzstartflag(i) = .True.
             call wz_effect(i)
	     endif
         endif
      	end do
! --
! -- For all active incidents, check if any of them is ending during the
! -- current simulation interval, if yes call inci_remove to remove it 
! -- from the list of active incidents.  Then call inci_restore to adjust 
! -- the link capacity after removing the incident.
! --
      do i=1,WorkZoneNum
        if(tt.gt.WorkZone(i)%ET) then
	    if(wzstartflag(i)) then
	   	    wzstartflag(i) = .False.
            call wz_restore(i)
	    endif
        endif 
      end do

	end subroutine


! =============================================
	subroutine WZ_effect(i)
! --
! -- This subroutine reduces the link lane.mile according to the incident
! -- severity.
! --
! -- This subroutine is called from inci_check
! -- This subroutine does not call any subroutines
! --
! -- INPUT :
! --   ilink : the link on which the incident occured
! --   seve : severity of the incident
! --
! -- OUTPUT :
! --   Reduced lane.mile length and sturation flow rate for link "ilink".
! --
      use muc_mod 
! --
      seve=WorkZone(i)%CapRed  
      ilink=GetFLinkFromNode(WorkZone(i)%FNode,WorkZone(i)%TNode)

! -- Keep original value      
!	  WorkZone(i)%OrigDisChg=MaxFlowRate(ilink)


	  WorkZone(i)%OrigDisChg=MaxFlowRateOrig(ilink)

	  WorkZone(i)%OrigSpdLmt=SpeedLimit(ilink)

! -- apply work zone value      
	  xl(ilink)=nlanes(ilink)*s(ilink)*(1-seve)
!      MaxFlowRate(ilink)=WorkZone(i)%Discharge/3600.0*nlanes(ilink)


      MaxFlowRateOrig(ilink)=WorkZone(i)%Discharge/3600.0*nlanes(ilink)

	  SpeedLimit(ilink)=WorkZone(i)%SpeedLmt


	end subroutine



! =============================================
	subroutine WZ_restore(i)
! --
! -- This subroutine restores the tane.mile length and saturation flow
! -- rate to their original value.
! --
! -- This subroutine is called from inci_check after the incident is cleared.
! -- This subroutine does not call any subroutines. 
! --
! -- INPUT :
! --   ilink : the link on which the incident occured
! --   seve : severity of the incident
! --
! -- OUTPUT :
! --   Restored lane.mile length and sturation flow rate for link "ilink". 
! --
      	use muc_mod 
! --
      ilink=GetFLinkFromNode(WorkZone(i)%FNode,WorkZone(i)%TNode)

! -- restore original value
      xl(ilink)=nlanes(ilink)*s(ilink)


!      MaxFlowRate(ilink)=WorkZone(i)%OrigDisChg

      MaxFlowRateOrig(ilink)=WorkZone(i)%OrigDisChg
	  
	SpeedLimit(ilink)=WorkZone(i)%OrigSpdLmt
	end subroutine

