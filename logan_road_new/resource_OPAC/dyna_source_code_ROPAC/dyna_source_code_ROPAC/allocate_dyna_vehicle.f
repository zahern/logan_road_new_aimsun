      subroutine allocate_dyna_vehicle

      use muc_mod
      use vector_mod

      integer error


!      print *, 'MaxVehicles', MaxVehicles
!      print *, 'Please enter nu_ve below.....'
!	read(*,*) nu_ve
	 
      nu_ve=max(10,(MaxVehicles)+10+nubus)


c --  pathindex(i) : the number of nodes in the path of vehicle i.
      
	allocate(pathindex(nu_ve),stat=error)
      if(error.ne.0) then
	  write(911,*) "allocate pathindex error - insufficient memory"
	  stop
	endif
	pathindex(:) = 1

      
	allocate(RemainDwell(nu_ve),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate RemainDwell error - insufficient memory'
	  stop
	endif
	RemainDwell(:) = 0
	
	allocate(HOVFlag(nu_ve),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate HOVFlag error - insufficient memory'
	  stop
	endif
	HOVFlag(:) = .False.

	allocate(HOTFlag(nu_ve),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate HOTFlag error - insufficient memory'
	  stop
	endif
	HOTFlag(:) = .False.

c	print *,'Alexcheck01  nu_ve =',nu_ve
c	pause

	allocate(DestVisit(nu_ve),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate DestVisit error - insufficient memory'
	  stop
	endif
	DestVisit(:) = 1
	
	allocate (decision(nu_ve), stat=error)
      if(error.ne.0) then
	  write(911,*) 'allocate decision error - insufficient memory'
	  stop
	endif
	decision(:)=0

	allocate (switch(nu_ve),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate switch error - insufficient memory'
	  stop
	endif
	switch(:)=1

	allocate (ivms(nu_ve),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate ivms error - insufficient memory'
	  stop
	endif
	ivms(:)=0

      allocate (ttstop(nu_ve),stat=error)
  	if(error.ne.0) then
	  write(911,*) 'allocate ttstop error - insufficient memory'
	  stop
	endif
 	ttstop(:)=0
 	  
  	allocate (ttilnow(nu_ve),stat=error)
   	if(error.ne.0) then
	  write(911,*) 'allocate titlnow error - insufficient memory'
	  stop
	endif
 	ttilnow(:)=0

   	allocate (ribf(nu_ve),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate ribf error - insufficient memory'
	  stop
	endif
	ribf(:)=0

	allocate (notin(nu_ve),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate notin error - insufficient memory'
	  stop
	endif
	notin(:)=0

	allocate (tleft(nu_ve),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate tleft error - insufficient memory'
	  stop
	endif
	tleft(:)=0

	allocate (tqwait(nu_ve),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate tqwait error - insufficient memory'
	  stop
	endif
	tqwait(:)=0

 	allocate (compliance(nu_ve),stat=error)
 	if(error.ne.0) then
	  write(911,*) 'allocate compliance error - insufficient memory'
	  stop
	endif
	compliance(:)=0

	allocate (mtnum(nu_ve),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate mtnum error - insufficient memory'
	  stop
	endif
	mtnum(:)=1
      
	allocate (atime(nu_ve),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate atime error - insufficient memory'
	  stop
	endif
      atime(:)=0
      
	allocate (distans(nu_ve),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate distans error - insufficient memory'
	  stop
	endif
	distans(:)=0

      allocate (qflag(nu_ve),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate qflag error - insufficient memory'
	  stop
	endif
	qflag(:)=.False.
	  	
	allocate (info(nu_ve),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate info error - insufficient memory'
	  stop
	endif
	info(:)=0

      allocate (nexlink(nu_ve),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate nexlink error - insufficient memory'
	  stop
	endif
	nexlink(:)=0
      
	allocate (tocross(nu_ve),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate tocross error - insufficient memory'
	  stop
	endif
	tocross(:)=0

c ----------------------------------------
c ----------------------------------------
      if(iteration.eq.0) then

      allocate(nnpath(nu_ve),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate nnpath error - insufficient memory'
	  stop
	endif
	nnpath(:) = 0

      allocate(NoOfIntDst(nu_ve),stat=error)
	if(error.ne.0) then
	  write(911,*)'allocate NoOfIntDst error - insufficient memory'
	  stop
	endif
	NoOfIntDst(:) = 0
      
      allocate(IntDestZone(nu_ve,noofstops),stat=error)
	if(error.ne.0) then
	  write(911,*)'allocate IntDestZone error-insufficient memory'
	  stop
	endif
	IntDestZone(:,:) = 0

      allocate(IntDestPath(nu_ve,noofstops),stat=error)
	if(error.ne.0) then
	  write(911,*)'allocate IntDestPath error-insufficient memory'
	  stop
	endif
	IntDestPath(:,:) = 0
      
	allocate(IntDestDwell(nu_ve,noofstops),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate IntDestDwell error-insufficient memory'
	  stop
	endif
	IntDestDwell(:,:) = 0

	allocate(iuserpath(nu_ve),stat=error)
	if(error.ne.0) then
	  write(911,*)'allocate iuserpath error-insufficient memory'
	  stop
	endif
	iuserpath(:)=0

      allocate(lt(nu_ve),stat=error)
	if(error.ne.0) then 
	  write(911,*) 'allocate lt error - insufficient memory'
	  stop
	endif
	lt(:)=1

	allocate (ioc(nu_ve),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate ioc error - insufficient memory'
	  stop
	endif
	ioc(:)=1

	allocate (itag(nu_ve),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate itag error-insufficient memory'
	  stop
	endif
	itag(:)=0

      allocate (isec(nu_ve),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate isec error-insufficient memory'
	  stop
	endif
	isec(:)=0

      allocate (stime(nu_ve),stat=error)
	if(error.ne.0) then
	  write(911,*)'allocate stime error-insufficient memory'
	  stop
	endif
	stime(:)=0

      allocate (xpar(nu_ve),stat=error)
	if(error.ne.0) then
	  write(911,*)'allocate xpar error-insufficient memory'
	  stop
	endif
	xpar(:)=0

      allocate (icurrnt(nu_ve),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate icurrnt error-insufficient memory'
	  stop
	endif
	icurrnt(:)=1

      allocate (jdest(nu_ve),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate jdest error-insufficient memory'
	  stop
	endif
	jdest(:)=0



      allocate (jorigin(nu_ve),stat=error)
	if(error.ne.0) then
	  write(911,*)'allocate jorigin error-insufficient memory'
	  stop
	endif
	jorigin(:)=0


      allocate(jipick(nu_ve),stat=error)
	if(error.ne.0) then
	  write(911,*)'allocate jipick error-insufficient memory'
	  stop
	endif
	jipick(:)=0


      allocate (vehclass(nu_ve),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate vehclass error-insufficient memory'
	  stop
	endif
	vehclass(:)=0

      allocate (vehclass2(nu_ve),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate vehclass2 error-insufficient memory'
	  stop
	endif
	vehclass2(:)=0

      call VhcAtt_2DSetup(nu_ve)
  	do icount = 1, nu_ve
        call VhcAtt_Setup(icount,10)
      enddo


c --- Bus arrays

	if(nubus.gt.0) then
	
      call BusAtt_2DSetup(nubus)
  	do icount = 1, nubus
        call BusAtt_Setup(icount,10)
      enddo

      allocate (NoBusNode(nubus),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate NoBusNode error-insufficient memory'
	  stop
	endif
	NoBusNode(:)=0
	
      allocate (busid(nubus),stat=error)
	if(error.ne.0) then
	  write(911,*)'allocate busid error-insufficient memory'
	  stop
	endif
      busid(:)=0

	allocate (buslink(nubus),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate buslink error-insufficient memory'
	  stop
	endif
	buslink(:)=0
	
      allocate (ngenbus(nubus),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate ngenbus error-insufficient memory'
	  stop
	endif
	ngenbus(:)=0
 	
      allocate (bustime(nubus),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate bustime error-insufficient memory'
	  stop
	endif
	bustime(:)=0
 	
      allocate (busstart(nubus),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate busstart error-insufficient memory'
	  stop
	endif
	busstart(:)=0
    	
      allocate (busdwell(nubus),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate busdwell error-insufficient memory'
	  stop
	endif
	busdwell(:)=0
	
      else
 	
      call BusATT_2DSetup(1)
  	do icount = 1, 1
        call BusATT_Setup(icount,1)
      enddo

      allocate (NoBusNode(1),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate NoBusNode error-insufficient memory'
	  stop
	endif
	NoBusNode(:)=0
	
      allocate (busid(1),stat=error)
	if(error.ne.0) then
	  write(911,*)'allocate busid error-insufficient memory'
	  stop
	endif
	busid(:)=0
	
      allocate (buslink(1),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate buslink error-insufficient memory'
	  stop
	endif
	buslink(:)=0
	
      allocate (ngenbus(1),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate ngenbus error-insufficient memory'
	  stop
	endif
	ngenbus(:)=0
 	
      allocate (bustime(1),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate bustime error-insufficient memory'
	  stop
	endif
	bustime(:)=0
 	
      allocate (busstart(1),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate busstart error-insufficient memory'
	  stop
	endif
	busstart(:)=0
    	
      allocate (busdwell(1),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate busdwell error-insufficient memory'
	  stop
	endif
	busdwell(:)=0
	
      endif
	
      endif

      if(inci_num.gt.0.or.WorkZoneNum.gt.0) then
     	allocate(ImpactType(nu_ve),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate ImpactType error - 
     +  insufficient memory'
	  stop
	endif
 	ImpactType(:)%WZMode = 0
 	ImpactType(:)%InciMode = 0
 	ImpactType(:)%InciIM = 0 	
	ImpactType(:)%WZIM = 0

      endif
c ---------------------------------------------

      return
      end
