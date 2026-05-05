      subroutine vehicle_transfer(l,t,tend)
c --
c -- This subroutine is responsible for moving the vehicles from one link
c -- to another and updating the link information accordingly.
c --
c -- This subroutine is called from vehicle_simulation every simulation interval.
c -- This subroutine calls penlaty_calculation
c --
c -- INPUT :
c --   l : current simulation interval
c --   t : starting clock time of the current simulation interval
c --   tend : ending clock time of the current simulation interval.
c --
c -- OUTPUT :
c -- updated link and vehicle information.
c --
      use muc_mod
      use vector_mod
      use LinkList_mod
      use Intooi_mod
      type(linkstruct),pointer::pass
      INTEGER ImDest
      integer Index1D
      real value
      integer ncan1,ncan2,ncan3,ncan4,ncan5,ncan6
      integer TKInd
      logical MFlag
c --
c -- Loop over all links   
c --
      
      do 9 i=1,noofarcs
c --
c --  calculate the free space on link i       
      linfree(i)=(maxden*xl(i)-volume(i))
      
c -- Initialize isel for all vehicles ready to move into link i.
c --
      isel(:)=0
c --
c -- Calculate the number of vehicles to enter link i (nc).  
c -- nc is the minimum of 3 values
c --  a. ncan: the maximum available space on the link
c --  b. intoo(i): the number of vehicles ready to move into link i.
c --
c -- NOTE : a and b are checks for the supply while c is a check for the 
c --        demand
c -- 
	
      ncan1=ifix(maxden*xl(i)-(npar(i)-nTruck(i))+2.0*nTruck(i)) ! for checking physical capacity, should use physical PCE
	ncan2=min(Intoo(i)%NVehOut,nint(aveoutflow(i)*60*tii))
      ncan3=intoo(i)%NVehIn
	ncan4=maxden*xl(i)
	ncan5=ncan1+ncan2
	ncan6=ncan1+ncan2*0.5
      if(topocont(i).eq.0)then ! all downstream link # are larger than i (scan later than i)
        nc=max(0,min(ncan5,ncan3,ncan4))
      elseif(topocont(i).eq.llink(i,nu_mv+1))then
	  nc=max(0,min(ncan1,ncan3,ncan4))
	else
        nc=max(0,min(ncan6,ncan3,ncan4))
	endif
c --
c -- Pick the first nc vehicle out of the intoo.
c --
c -- find the vehicle with the earliest link-end-arrival      
c -- time among the 'nc' vehicles to be moved in.   
c --
      if(nc.gt.0)then

      do 11 nb=1,nc

        tma=-100.0
        do k=1,intoo(i)%NVehIn
          if(isel(k).eq.0)then

	       If(TranLink_Value(i,k,1).lt.1)then
               print *, 'TranLink_Value(i,k,1) error'
	       endif
             tl=tqwait(TranLink_Value(i,k,1))
!            tl=tqwait(intooi(i,k,1))
             if(tl.eq.0) t1=tleft(TranLink_Value(i,k,1))
!            if(tl.eq.0) tl=tleft(intooi(i,k,1))

            if(tl.gt.tma)then
              tma=tl
              mk=k
            endif
          endif
        enddo
c --
c -- mk : the vehicle rank (out of the intoo vehicles) 
c --
c -- this vehicle is moved to link i
c --
c -- in : the incoming link for the current vehicle
c --  j : the vehicle ID for the current vehicle
c --  kj: is the vehicle rank on link in.
c -- isel(mk) is set to 1 to indicate that the vehicle has moved to
c -- the next link
c -- 

          in=TranLink_Value(i,mk,2)
          j=TranLink_Value(i,mk,1)
          kj=TranLink_Value(i,mk,3)
!         in=intooi(i,mk,2)
!         j =intooi(i,mk,1)
!         kj=intooi(i,mk,3)
          isel(mk)=1


c --  check if the link can accommodate this vehicle, if not, quit the loop
	   if(maxden*xl(i)-(partotal(i)+mtnum(j)).lt.0) exit

c --    
c -- record some path information for current vehicle.
c --
C	print *, 'Alex1000',j,icurrnt(j),t-stime(j)
      call VhcAtt_Insert(j,icurrnt(j),3,t-stime(j))

!      call VhcAtt_Insert(j,icurrnt(j),3,(t+tend)/2-stime(j))


	if(realdm.eq.1.or.(realdm.ne.1.and.NoOfIntDst(j).eq.1)) then
	 ImDest = 1
	else
	 ImDest = DestVisit(j)
	endif

      if(nint(VhcAtt_value(j,icurrnt(j),1)).eq.
     +  destination(MasterDest(IntDestZone(j,ImDest))))then
        value = ttstop(j) + IntDestDwell(j,Imdest)
      else
        value = ttstop(j)
      endif
C	print *, 'Alex1001',j,icurrnt(j),value
      call VhcAtt_Insert(j,icurrnt(j),2,value)

      if(icurrnt(j)-1.gt.0) then
        Index1D = icurrnt(j)-1
!        value = ttilnow(j)-VhcAtt_value(j,Index1D,3)
        value = t-stime(j)-VhcAtt_value(j,Index1D,3)

      else
        value = ttilnow(j)
      endif

      call VhcAtt_Insert(j,icurrnt(j),4,value)

c --
c -- If the vehicle was in the queue, then reset the waiting time and
c -- the qflag for the current vehicle.
c --
        if(qflag(j)) then
          qflag(j)=.False.
          tqwait(j)=0.0
        endif
c --
c -- check if this is a switch for the current vehicle
c --
         if(info(j).eq.1) then
           if(switch(j).lt.0) switch(j)=iabs(switch(j))+1
         endif

c  --
c  -- define the movement for the current vehicle
c  --
         do ii=1,llink(in,nu_mv+1)
           if(i.eq.llink(in,ii)) moveturn=move(in,ii)
         end do
c --
c -- calculate outflow and outleft for the current simulation interval.
c --
         if(moveturn.eq.1) outleft(in)=outleft(in)+1
         outflow(in)=outflow(in)+1

c --   
c -- calculate the vehicle position.   
c -- add the time left to its time-till-now array.
c --
         xpar(j)=s(i)-(v(i)*tleft(j))
         ttilnow(j) = ttilnow(j) + tleft(j)
c --     add to GUITotalTime
         GuiTotalTime=GuiTotalTime+tleft(j)

c --
c -- if the vehicle is crossing the current link during tleft, then
c -- set the position of the vehicle to be the end of the link.
c --
         if(xpar(j).lt.0.0) then
           xpar(j)=0.0
           distans(j)=distans(j)+s(i)        
         else
           distans(j)=distans(j)+(v(i)*tleft(j))
         endif
c --
c -- adjust the number of vehicles on the upstream link and remove
c -- the vehicle from the link's 'mtxj' array. 
c --

         call mtxj_remove(in,j)

         npar(in)=npar(in)-1
         if(vehclass2(j).eq.2.or.vehclass2(j).eq.5.or.
     *      vehclass2(j).eq.7) nTruck(in)=nTruck(in)-1
	   volume(in)=volume(in)-1
         if(volume(i).lt.0) then
           write(911,*)'Negative volume on link',in
	     write(911,*)'Please contact developers'
           stop
         endif
         partotal(in)=partotal(in)-mtnum(j)
         nmov(in)=nmov(in)+1

c --
c --  add the vehicle to the current link's mtxj array. 
c --
	   call mtxj_insert(i,j) !LST

         npar(i)=npar(i)+1
         if(vehclass2(j).eq.2.or.vehclass2(j).eq.5.or.
     *      vehclass2(j).eq.7) nTruck(i)=nTruck(i)+1
	   volume(i)=volume(i)+1
         partotal(i)=partotal(i)+mtnum(j)
	   if(maxden*xl(i)-partotal(i).lt.0) then
	     write(911,*) 'Error!! Possibly wrong setting in vehicle'
	     write(911,*) ' type in scenario.dat'
	     stop
	   endif
c --
c -- increase icurrnt for the current vehicle
         icurrnt(j)=icurrnt(j)+1

11    continue
c --
c --  After moving nc vehicles, if there are still some vehicles ready to
c --  move into the current link, then keep these vehicles 
c --  on their current link's queue (i.e. on the upstream links).
c -- (i.e. check for the downstream conditions)
c --
         do k=1,intoo(i)%NVehIn
          if(isel(k).lt.1) then
             j  = TranLink_Value(i,k,1)
            in  = TranLink_Value(i,k,2)
!            j  = intooi(i,k,1)
!            in = intooi(i,k,2)
            if(.not.qflag(j)) then
              qflag(j)=.True.
              xpar(J)=0.0
            endif
            tqwait(j)=tqwait(j)+tleft(j)
            ttilnow(j) = ttilnow(j)+tleft(j)
            GuiTotalTime=GuiTotalTime+tleft(j)  ! -- add to GUITotalTime
          endif
         enddo

      endif ! nc.gt.1

c --  calculate truck % and get the PCE
      Mflag = .False.
	if(link_iden(i).lt.99.and.npar(i).gt.0.and.LGrade(i).gt.0) then
        TruckPct(i) = float(nTruck(i))/npar(i)
        if(nTruck(i).gt.0) then
	    do ii = 1, TruckNum
           if(TruckPct(i).lt.TruckBPnt(ii)/100.0) then
             TKInd = ii
             MFlag = .True.
             exit
           endif
	    enddo
	    if(.not.MFlag) TKInd = TruckNum
          DynPCE(i) = PCE(GRDInd(i),LENInd(i),TKInd) ! time-dependent PCE
	  else
          DynPCE(i) = 1.5
        endif !nTruck(i).gt.0
	else  ! for downgrade, the PCE remains 1.5
        DynPCE(i) = 1.5
	endif ! Link_iden.lt.90

9     continue
c --
c -- reinitialization of volume and vehicle_queue
c --
      partotal(:) = 0
      vehicle_queue(:) = 0

	!***************************************************

	!the % of link that is queue for 930.7B
	vehicle_queue_PCE(:)=0
	!*****************************************************

      do 21 i=1,noofarcs
c --  Update total PCE based on grade and length of the link
      PCEtmp = 0.0

c --  determine vehicle_queue
      pass=>LinkVehList(i)
      if(link_iden(i).lt.99) then
	do while(pass%veh.gt.0)
        j=pass%veh
        if(vehclass2(j).eq.2.or.vehclass2(j).eq.5.or.
     *     vehclass2(j).eq.7) then
	     mtnum(j) = DynPCE(i) ! update the PCE based on grade, length and truck %
	  else
	     mtnum(j) = 1
	  endif

	  if(qflag(j))  vehicle_queue(i)=vehicle_queue(i)+1
	!***************************************************
	
	!the % of link that is queue for 930.7B
	if(qflag(j)) then
	vehicle_queue_PCE(i)=vehicle_queue_PCE(i)+mtnum(j)
	endif
	!*****************************************************
	  partotal(i)=partotal(i)+mtnum(j)
	  pass=>pass%next_veh

	enddo        
      
	endif !link_iden(i).lt.99

21    continue
!	intooi(:,:,:) = 0
      do i = 1, noofarcs
        call TranLink_Clear(i,1)
      enddo
      nparold(:)=npar(:)

      end subroutine
