      subroutine calavg(Loop)
c --
      use muc_mod

	integer loop,aggindex,error
 

      if(iteration.eq.0.and..not.callavg) then
      
	allocate(astmpt(noofarcs),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate astmpt error - insufficent memory'
	  stop
	endif
	astmpt(:) = 0 
      
	allocate(apen(noofarcs,nu_mv),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate apen error - insufficient memory'
	  stop
	endif
	apen(:,:) = 0

	allocate(alet(noofarcs),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate alet error - insufficient memory'
	  stop
	endif
	alet(:) = 0
      
	allocate(diff(noofarcs,2),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate diff error - insufficient memory'
	  stop
	endif
	diff(:,:) = 0
	
      allocate(apenal(noofarcs,nu_mv),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate apenal error - insufficient memory'
	  stop
    	endif
	apenal(:,:) = 0
	
      allocate(lint(noofarcs),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate lint error - insufficient memory'
	  stop
	endif
	lint(:) = 0
      
	allocate(lfr(noofarcs),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate lfr error - insufficient memory'
	  stop
	endif
	lfr(:) = 0
	callavg = .True.
	
      endif
	
c -------------------------------------------------------
c ---------Forward * penalty needed by somarginal ---------
c -------------------------------------------------------

        do i=1,noofarcs
          do j=1,nu_mv
           apenal(i,j)=apenal(i,j)+openalty(i,j)


      if(iso_ok.eq.1) then
      openaltyMG_sim(i, Loop, j) = openalty(i,j);
	endif
! End

           if(MOD(Loop,ftr).eq.0)then
		   aggindex=Loop/ftr
	       openaltyMG(i,aggindex,j) = apenal(i,j)/ftr
c             if(openaltyMG(i,aggindex,j).gt.9.999) 
c     *                 openaltyMG(i,aggindex,j) = 9.999
	       apenal(i,j)=0.0
           endif
           end do
        end do

c -----------------------------------------------------------------------
c ---------Number of vehicles make left turn or other movements     -----
c ---------Needed by somarginal subroutine                          -----
c -----------------------------------------------------------------------
c --  turnveh(i,1): number of vehicles on link i that will make left turn
c --  turnveh(i,2:): number of vehicles on link i that will make other movement
       do i=1,noofarcs
	   if(npar(i)-turnvehso(i,1).lt.0) then
	     write(911,*) 'error in avg, turnveh'
	     stop
	   endif
         diff(i,1)=diff(i,1)+turnvehso(i,1)				!left turn
         diff(i,2)=diff(i,2)+npar(i)-turnvehso(i,1) !other movement


      if(iso_ok.eq.1) then
      moveturnMG_sim(i,Loop,1) = turnvehso(i,1)
	moveturnMG_sim(i,Loop,2) = npar(i)-turnvehso(i,1)
	if(moveturnMG_sim(i,Loop,2).lt.0) then
        moveturnMG_sim(i,Loop,2) = 0
	endif
	endif 
! End

         if(MOD(Loop,ftr).eq.0)then
           aggindex=Loop/ftr
           moveturnMG(i,aggindex,1) = diff(i,1)/ftr
           moveturnMG(i,aggindex,2) = diff(i,2)/ftr
           diff(i,1)=0
	   diff(i,2)=0
         endif
       end do

c ------------------------------------------------
c ---------Travel Time in original format ---------
c ------------------------------------------------

       do i=1,noofarcs
         astmpt(i)=astmpt(i)+statmpt(i)


      if(iso_ok.eq.1) then
      TravelTime_sim(i, Loop) = statmpt(i);
	endif
! End

         if(MOD(Loop,ftr).eq.0)then
	      aggindex=Loop/ftr
	      TravelTime(i,aggindex)=astmpt(i)/ftr
	      astmpt(i)=0.0
	   endif
       end do

c --------------------------------------------------
c --------- Link Entry Time in forward* -----------
c --------------------------------------------------

         do i=1,noofarcs
           alet(i)=alet(i)+link_entry_time(i)


	if(iso_ok.eq.1) then
      PenaltyEntry_sim(i,Loop) = link_entry_time(i);
	endif
! End
           if(MOD(Loop,ftr).eq.0)then
            aggindex = loop/ftr
            PenaltyEntry(i,aggindex)=alet(i)/ftr
            alet(i)=0.0
           endif
         end do
c ------------------------------------------
c --------- Penalty itself is in backward* -----------
c ----------TravelPenalty is backward*
c ------------------------------------------
         do i=1,noofarcs
           do j=1,nu_mv
            apen(i,j)=apen(i,j)+penalty(i,j)
            if(MOD(Loop,ftr).eq.0)then
             aggindex = loop/ftr
             avgpen=apen(i,j)/ftr
c             if(avgpen.gt.9.999) avgpen=9.99
             TravelPenalty(i,aggindex,j)=apen(i,j)/ftr
             apen(i,j)=0.0
            endif
           end do
         end do

c ---------------------------------------------------------
c ---------Avg Difference between
c ---------   Avg # of veh ready to move in link i 
c ---------   Avg # of free slots in link i
c ---------Needed by somarginal
c ---------Original format
c ---------------------------------------------------------
         do i=1,noofarcs
           lfr(i)=lfr(i)+intoo(i)%NVehIn
           lint(i)=lint(i)+linfree(i)


      if(iso_ok.eq.1) then
      DiffMG_sim(i,Loop) = intoo(i)%NVehIn - linfree(i)
	if(DiffMG_sim(i,Loop).lt.0) then
	  DiffMG_sim(i,Loop) = 0
	endif  
	endif
! End

           if(MOD(Loop,ftr).eq.0)then
             aggindex = loop/ftr
             DiffMG(i,aggindex)=max(0.0,(lfr(i)-lint(i)))/ftr
             lfr(i)=0
             lint(i)=0
           endif
         end do

           return
           end
